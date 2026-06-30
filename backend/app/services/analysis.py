"""Core analysis: file -> contributor map, bus factor, ownership %."""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from app.models.analysis import Contributor, FileAnalysis


# Single-author share above this threshold triggers bus factor = 1.
BUS_FACTOR_DOMINANCE_THRESHOLD = 0.50


def _resolve_author(commit: dict) -> str:
    """Prefer the GitHub login, fall back to the git commit author metadata."""
    author = (commit.get("author") or {})  # GitHub user (nullable)
    if author.get("login"):
        return author["login"]
    commit_meta = commit.get("commit") or {}
    author_meta = commit_meta.get("author") or {}
    return author_meta.get("name") or "unknown"


def _last_touched(commit: dict) -> str:
    """Return an ISO date string from a commit's author date."""
    commit_meta = commit.get("commit") or {}
    # Prefer the git author date; fall back to committer date.
    return (commit_meta.get("author", {}).get("date")
            or commit_meta.get("committer", {}).get("date")
            or "1970-01-01T00:00:00Z")


def build_contributor_map(commits: list[dict]) -> list[FileAnalysis]:
    """Aggregate raw commits into per-file contributor stats.

    GitHub's commits endpoint returns file metadata per commit only with the
    detailed view; our base endpoint returns one entry per commit (not per
    file). For the MVP we treat each commit as a unit and attribute it to the
    tracked paths the caller provides via `files_per_commit`. To keep the
    first sprint simple and dependency-light, this aggregates at the commit
    level and emits one FileAnalysis per commit's "primary" path when file
    data is unavailable.

    NOTE: Sprint 1 baseline uses per-commit author aggregation keyed to a
    synthetic single-file repo shape. File-level granularity is filled in
    Sprint 2 once we pull commit-detail (file list) per SHA.
    """
    # Group commits by a path key. For the baseline we bucket everything under
    # a representative sample by author to produce the contributor map shape
    # the API contract requires. Real file bucketing is layered in Sprint 2.
    by_path: dict[str, list[dict]] = defaultdict(list)
    # Placeholder bucketing: synthesize per-commit attribution to a single path
    # derived from the commit message / sha so the response shape is valid.
    for c in commits:
        path = _derive_path(c)
        by_path[path].append(c)

    results: list[FileAnalysis] = []
    for path, path_commits in by_path.items():
        results.append(_analyze_file(path, path_commits))
    return results


def _derive_path(commit: dict) -> str:
    """Best-effort path label for baseline aggregation.

    If the commit carries file metadata (`files`), use the first filename.
    Otherwise synthesize a stable placeholder so the response shape is valid
    and the API is testable. Sprint 2 replaces this with real per-file data.
    """
    files = commit.get("files") or []
    if files:
        return files[0].get("filename") or "unknown"
    sha = (commit.get("sha") or "")[:7]
    return f"commit-{sha}"


def _analyze_file(path: str, commits: list[dict]) -> FileAnalysis:
    per_author: dict[str, dict] = {}
    for c in commits:
        author = _resolve_author(c)
        entry = per_author.setdefault(
            author, {"commits": 0, "last_commit": "1970-01-01T00:00:00Z"}
        )
        entry["commits"] += 1
        date_str = _last_touched(c)
        if date_str > entry["last_commit"]:
            entry["last_commit"] = date_str

    total = sum(e["commits"] for e in per_author.values())
    contributors = sorted(
        (
            Contributor(
                author=author,
                commits=e["commits"],
                last_commit=_iso_date(e["last_commit"]),
                ownership_pct=round(e["commits"] / total * 100, 2) if total else 0.0,
            )
            for author, e in per_author.items()
        ),
        key=lambda x: x.commits,
        reverse=True,
    )
    return FileAnalysis(
        path=path,
        contributors=contributors,
        total_commits=total,
        bus_factor=_bus_factor(contributors, total),
    )


def _bus_factor(contributors: list[Contributor], total: int) -> int:
    """Bus factor: how many top contributors account for >50% of commits."""
    if total == 0 or not contributors:
        return 0
    cumulative = 0
    for i, c in enumerate(contributors, start=1):
        cumulative += c.ownership_pct
        if cumulative > (BUS_FACTOR_DOMINANCE_THRESHOLD * 100):
            return i
    return len(contributors)


def _iso_date(iso_ts: str) -> str:
    """Trim an ISO timestamp down to a date string for the response."""
    try:
        return date.fromisoformat(iso_ts[:10]).isoformat()
    except (ValueError, TypeError):
        return iso_ts[:10]
