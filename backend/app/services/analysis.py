"""Core analysis: file -> contributor map, bus factor, ownership %.

Consumes commits enriched with a `files` list (from the per-commit detail
endpoint). Each commit is attributed to every file in its `files[].filename`.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from app.models.analysis import Contributor, FileAnalysis


# Single-author share above this threshold triggers bus factor = 1.
BUS_FACTOR_DOMINANCE_THRESHOLD = 0.50


def _resolve_author(commit: dict) -> str:
    """Prefer the GitHub login, fall back to the git commit author metadata."""
    author = commit.get("author") or {}  # GitHub user (nullable)
    if author.get("login"):
        return author["login"]
    commit_meta = commit.get("commit") or {}
    author_meta = commit_meta.get("author") or {}
    return author_meta.get("name") or "unknown"


def _last_touched(commit: dict) -> str:
    """Return an ISO timestamp string from a commit's author date."""
    commit_meta = commit.get("commit") or {}
    return (commit_meta.get("author", {}).get("date")
            or commit_meta.get("committer", {}).get("date")
            or "1970-01-01T00:00:00Z")


def build_contributor_map(commits: list[dict]) -> list[FileAnalysis]:
    """Aggregate commits (each carrying a `files` list) into per-file stats.

    A single commit touching multiple files contributes to each of those files'
    contributor counts. Falls back to synthetic per-commit bucketing only when a
    commit carries no `files` data.
    """
    by_path: dict[str, list[dict]] = defaultdict(list)

    for commit in commits:
        files = commit.get("files") or []
        if files:
            for f in files:
                path = (f.get("filename") or f.get("previous_filename")
                        or "unknown")
                by_path[path].append(commit)
        else:
            # No file data available — bucket under a synthetic path so the
            # response shape stays valid.
            by_path[_synthetic_path(commit)].append(commit)

    return [_analyze_file(path, path_commits)
            for path, path_commits in by_path.items()]


def _synthetic_path(commit: dict) -> str:
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
