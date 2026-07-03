"""Core analysis: file -> contributor map, bus factor, ownership %, decay detection."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime

from app.config import get_settings
from app.models.analysis import Contributor, Decay, FileAnalysis
from app.models.analysis_config import AnalysisConfig


def _resolve_author(commit: dict) -> str:
    """Prefer the GitHub login, fall back to the git commit author metadata."""
    author = commit.get("author") or {}
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


def build_contributor_map(commits: list[dict], config: AnalysisConfig | None = None) -> list[FileAnalysis]:
    """Aggregate commits into per-file stats."""
    if config is None:
        config = AnalysisConfig()

    by_path: dict[str, list[dict]] = defaultdict(list)

    for commit in commits:
        files = commit.get("files") or []
        if files:
            for f in files:
                path = (f.get("filename") or f.get("previous_filename")
                        or "unknown")
                by_path[path].append(commit)
        else:
            by_path[_synthetic_path(commit)].append(commit)

    all_authors: set[str] = set()
    for commit in commits:
        author = _resolve_author(commit)
        all_authors.add(author)

    total_contributors_across_repo = len(all_authors)

    analyses = []
    for path, path_commits in by_path.items():
        analysis = _analyze_file(path, path_commits, config, total_contributors_across_repo)
        analyses.append(analysis)

    return analyses


def _synthetic_path(commit: dict) -> str:
    sha = (commit.get("sha") or "")[:7]
    return f"commit-{sha}"


def _analyze_file(path: str, commits: list[dict], config: AnalysisConfig | None = None, total_contributors_across_repo: int | None = None) -> FileAnalysis:
    """Analyze a single file."""
    if config is None:
        config = AnalysisConfig()

    per_author: dict[str, dict] = {}
    all_commit_dates: list[str] = []

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

    owner_ts = None
    for d in per_author_data:
        if d["author"] == contributors[0].author:
            owner_ts = d["last_commit_ts"]
            break

    decay_info = _calculate_decay(contributors, commits, all_commit_dates, owner_ts, config, total_contributors_across_repo)
    return FileAnalysis(
        path=path,
        contributors=contributors,
        total_commits=total,
        bus_factor=_bus_factor(contributors, total, config),
        decay=decay_info,
    )


def _bus_factor(contributors: list[Contributor], total: int, config: AnalysisConfig | None = None) -> int:
    """Bus factor: how many top contributors account for >threshold% of commits."""
    if config is None:
        config = AnalysisConfig()

    if total == 0 or not contributors:
        return 0
    cumulative = 0
    for i, c in enumerate(contributors, start=1):
        cumulative += c.ownership_pct
        if cumulative > (config.bus_factor_threshold * 100):
            return i
    return len(contributors)


def _iso_date(iso_ts: str) -> str:
    """Trim an ISO timestamp down to a date string."""
    try:
        return date.fromisoformat(iso_ts[:10]).isoformat()
    except (ValueError, TypeError):
        return iso_ts[:10]


def _parse_iso_datetime(ts: str) -> datetime | None:
    """Parse ISO timestamp string (handles 'Z' suffix for UTC)."""
    try:
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
    config: AnalysisConfig | None = None,
    total_contributors_across_repo: int | None = None,
) -> Decay | None:
    """Calculate decay status for a file."""
    if config is None:
        config = AnalysisConfig()

    # SOLO-DEVELOPER DETECTION
    if len(contributors) == 1:
        if total_contributors_across_repo == 1:
            owner = contributors[0]
            return Decay(
                status="critical",
                owner=owner.author,
                owner_last_commit=owner.last_commit,
                days_since_owner_touched=0,
                commits_since_owner_left=0,
                pct_changed_since_owner_left=0.0,
                solo_developer=True,
            )
        else:
            return None

    if not contributors or len(contributors) < 2:
        return None

    owner = contributors[0]

    if owner_last_ts is None:
        return None

    most_recent_ts = None
    for date_str in all_commit_dates:
        ts = _parse_iso_datetime(date_str)
        if ts is not None:
            if most_recent_ts is None or ts > most_recent_ts:
                most_recent_ts = ts

    if most_recent_ts is None:
        return None

    days_since_owner_touched = (most_recent_ts - owner_last_ts).days

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

    if days_since_owner_touched <= config.decay_warning_days or commits_since_owner_left == 0:
        status = "stable"
    elif (days_since_owner_touched >= config.decay_critical_days
          and commits_since_owner_left >= config.decay_critical_commits):
        status = "critical"
    elif pct_changed_since_owner_left >= config.decay_critical_change_pct:
        status = "critical"
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