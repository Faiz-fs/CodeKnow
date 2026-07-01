"""Core analysis: file -> contributor map, bus factor, ownership %, decay detection.

Consumes commits enriched with a `files` list (from the per-commit detail
endpoint). Each commit is attributed to every file in its `files[].filename`.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime

from app.config import get_settings
from app.models.analysis import Contributor, Decay, FileAnalysis


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
    # Track per-author stats, full timestamps for decay, and all commit dates.
    per_author: dict[str, dict] = {}
    all_commit_dates: list[str] = []  # Track all commit timestamps for decay

    for c in commits:
        author = _resolve_author(c)
        date_str = _last_touched(c)
        all_commit_dates.append(date_str)

        entry = per_author.setdefault(
            author, {"commits": 0, "last_commit_ts": "1970-01-01T00:00:00Z"}
        )
        entry["commits"] += 1
        if date_str > entry["last_commit_ts"]:
            entry["last_commit_ts"] = date_str

    total = sum(e["commits"] for e in per_author.values())
    # Build per-author data with date-only for response, but retain timestamp for decay.
    per_author_data = []
    for author, e in per_author.items():
        ts = _parse_iso_datetime(e["last_commit_ts"])
        last_commit_date = _iso_date(e["last_commit_ts"])
        per_author_data.append({
            "author": author,
            "commits": e["commits"],
            "last_commit_date": last_commit_date,
            "last_commit_ts": ts,
        })

    contributors = sorted(
        (
            Contributor(
                author=d["author"],
                commits=d["commits"],
                last_commit=d["last_commit_date"],
                ownership_pct=round(d["commits"] / total * 100, 2) if total else 0.0,
            )
            for d in per_author_data
        ),
        key=lambda x: x.commits,
        reverse=True,
    )

    # Find owner timestamp for decay calculation.
    owner_ts = None
    for d in per_author_data:
        if d["author"] == contributors[0].author:
            owner_ts = d["last_commit_ts"]
            break

    decay_info = _calculate_decay(contributors, commits, all_commit_dates, owner_ts)
    return FileAnalysis(
        path=path,
        contributors=contributors,
        total_commits=total,
        bus_factor=_bus_factor(contributors, total),
        decay=decay_info,
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


def _parse_iso_datetime(ts: str) -> datetime | None:
    """Parse ISO timestamp string (handles 'Z' suffix for UTC)."""
    try:
        # Handle ISO format with 'Z' suffix (UTC indicator)
        if ts.endswith('Z'):
            ts = ts[:-1] + '+00:00'
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError, AttributeError):
        return None


def _calculate_decay(
    contributors: list[Contributor],
    commits: list[dict],
    all_commit_dates: list[str],
    owner_last_ts: datetime | None,
) -> Decay | None:
    """Calculate decay status for a file based on owner inactivity.

    Returns None if there's insufficient data (single contributor only).
    The owner_last_ts parameter is the pre-parsed datetime of the owner's last commit.
    """
    if not contributors or len(contributors) < 2:
        # No decay risk if only one contributor — they're still active by definition.
        return None

    settings = get_settings()
    owner = contributors[0]

    if owner_last_ts is None:
        return None

    # Find the most recent commit date on this file (by ANY contributor).
    most_recent_ts = None
    for date_str in all_commit_dates:
        ts = _parse_iso_datetime(date_str)
        if ts is not None:
            if most_recent_ts is None or ts > most_recent_ts:
                most_recent_ts = ts

    if most_recent_ts is None:
        return None

    # Calculate days since owner's last touch.
    days_since_owner_touched = (most_recent_ts - owner_last_ts).days

    # Count commits by others after the owner's last commit.
    owner_last_date = owner_last_ts.date()
    commits_since_owner_left = 0
    for c in commits:
        commit_author = _resolve_author(c)
        if commit_author != owner.author:
            date_str = _last_touched(c)
            ts = _parse_iso_datetime(date_str)
            if ts is not None and ts.date() > owner_last_date:
                commits_since_owner_left += 1

    total = sum(c.commits for c in contributors)
    pct_changed_since_owner_left = round(
        commits_since_owner_left / total * 100, 2
    ) if total else 0.0

    # Determine decay status based on thresholds.
    # Order matters: check stable first (covers both conditions), then critical,
    # then decaying as the default middle state.
    # stable: owner touched within warning_days OR no commits by others since they left.
    if days_since_owner_touched <= settings.decay_warning_days or commits_since_owner_left == 0:
        status = "stable"
    # critical: either (critical_days+ days AND critical_commits+ commits) OR
    #           (critical_change_pct of total commits after owner left).
    elif (days_since_owner_touched >= settings.decay_critical_days
          and commits_since_owner_left >= settings.decay_critical_commits):
        status = "critical"
    elif pct_changed_since_owner_left >= settings.decay_critical_change_pct:
        status = "critical"
    # decaying: owner hasn't touched in warning_days+ days AND at least warning_commits by others.
    else:
        status = "decaying"

    return Decay(
        status=status,
        owner=owner.author,
        owner_last_commit=owner.last_commit,
        days_since_owner_touched=days_since_owner_touched,
        commits_since_owner_left=commits_since_owner_left,
        pct_changed_since_owner_left=pct_changed_since_owner_left,
    )
