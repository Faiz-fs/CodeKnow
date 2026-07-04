"""Repository analysis endpoint.

POST /codeknow/analyze/repo  ->  { repo_url: "https://github.com/owner/repo" }
Protected by JWT auth. Pulls commit history with per-file detail, builds the
contributor map + bus factor, persists the result, and returns it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import unquote
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.core.errors import (
    GitHubAPIError,
    InvalidRepoURLError,
    RepoNotFoundError,
    TokenDecryptionError,
)
from app.core.repo import normalize_repo_full_name, parse_repo_url
from app.core.security import decrypt_token
from app.db import get_db
from app.models.analysis import RepoAnalysisResponse, AnalyzeRequest
from app.models.analysis_config import AnalysisConfig
from app.models.repo_analysis import RepoAnalysis
from app.models.user import User
from app.services import analysis, github
from pydantic import BaseModel

router = APIRouter()

class AtRiskFile(BaseModel):
    path: str
    decay_status: str
    owner: str
    days_since_owner_touched: int
    commits_since_owner_left: int
    pct_changed_since_owner_left: float


class AtRiskResponse(BaseModel):
    repo: str
    analyzed_at: str
    total_at_risk: int
    files: list[AtRiskFile]


async def _persist_repo_analysis(
    db: AsyncSession,
    user_id: str,
    repo_full_name: str,
    now: datetime,
    raw_result: dict,
) -> None:
    """Upsert analysis row, preserving repo_analysis_id on re-analyze."""
    upsert_stmt = (
        pg_insert(RepoAnalysis)
        .values(
            id=str(uuid4()),
            user_id=user_id,
            repo_full_name=repo_full_name,
            platform="github",
            analyzed_at=now,
            raw_result=raw_result,
        )
        .on_conflict_do_update(
            constraint="uq_user_repo",
            set_={
                "analyzed_at": now,
                "raw_result": raw_result,
            },
        )
    )
    try:
        await db.execute(upsert_stmt)
        await db.commit()
    except ProgrammingError as exc:
        await db.rollback()
        if "uq_user_repo" not in str(getattr(exc, "orig", exc)):
            raise
        # DB not yet at migration 0003 — fall back until migrations run
        result = await db.execute(
            select(RepoAnalysis)
            .where(RepoAnalysis.repo_full_name == repo_full_name)
            .where(RepoAnalysis.user_id == user_id)
            .order_by(RepoAnalysis.analyzed_at.desc())
            .limit(1)
        )
        record = result.scalars().first()
        if record:
            record.analyzed_at = now
            record.raw_result = raw_result
        else:
            db.add(RepoAnalysis(
                user_id=user_id,
                repo_full_name=repo_full_name,
                platform="github",
                analyzed_at=now,
                raw_result=raw_result,
            ))
        await db.commit()


@router.post("/repo", response_model=RepoAnalysisResponse)
async def analyze_repo(
    req: AnalyzeRequest,
    max_commits: int = Query(default=500, ge=10, le=5000),
    decay_warning_days: int = Query(default=60, ge=7, le=365),
    decay_critical_days: int = Query(default=90, ge=14, le=730),
    decay_critical_commits: int = Query(default=3, ge=1, le=50),
    decay_critical_change_pct: float = Query(default=30.0, ge=5.0, le=100.0),
    bus_factor_threshold: float = Query(default=0.50, ge=0.1, le=0.9),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    owner, repo = parse_repo_url(req.repo_url)
    repo_full_name = f"{owner}/{repo}"

    # Decrypt the user's stored GitHub token for authenticated API calls.
    if not user.github_access_token_encrypted:
        raise TokenDecryptionError("No GitHub token stored for this user")
    try:
        token = decrypt_token(user.github_access_token_encrypted)
    except ValueError as e:
        raise TokenDecryptionError(f"Failed to decrypt stored token: {e}") from e

    # Validate config parameters
    if decay_critical_days <= decay_warning_days:
        raise InvalidRepoURLError(
            f"decay_critical_days ({decay_critical_days}) must be greater than decay_warning_days ({decay_warning_days})"
        )

    # Build config from query parameters
    config = AnalysisConfig(
        max_commits=max_commits,
        decay_warning_days=decay_warning_days,
        decay_critical_days=decay_critical_days,
        decay_critical_commits=decay_critical_commits,
        decay_critical_change_pct=decay_critical_change_pct,
        bus_factor_threshold=bus_factor_threshold,
    )

    client = github.GitHubClient(token=token)
    try:
        commits = await client.get_commits_with_details(owner, repo)
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        if status == 404:
            raise GitHubAPIError(f"Repository {owner}/{repo} not found")
        if status == 403:
            raise GitHubAPIError(
                "GitHub API forbidden — token may lack scope or be rate-limited",
            )
        raise GitHubAPIError(f"GitHub API error ({status}): {e}") from e
    except httpx.HTTPError as e:
        raise GitHubAPIError(f"GitHub API error: {e}") from e
    finally:
        await client.close()

    # Apply config max_commits to commits list
    commits = commits[:config.max_commits]

    # Build contributor map with config
    files = analysis.build_contributor_map(commits, config=config)

    # ✅ FIXED: Use _resolve_author for safe author extraction
    total_contributors = len(set(
        analysis._resolve_author(commit)
        for commit in commits if commit
    ))

    # Check if solo dev (single contributor across entire repo)
    solo_developer_repo = total_contributors == 1

    now = datetime.now(timezone.utc)
    response = RepoAnalysisResponse(
        repo=repo_full_name,
        analyzed_at=now.isoformat(),
        files=files,
        total_contributors=total_contributors,
        solo_developer_repo=solo_developer_repo,
        config_used=config.to_dict(),
    )

    raw_result = response.model_dump(mode="json")

    await _persist_repo_analysis(
        db=db,
        user_id=str(user.id),
        repo_full_name=repo_full_name,
        now=now,
        raw_result=raw_result,
    )

    return response



@router.get("/repo/at-risk", response_model=AtRiskResponse)
async def get_at_risk_files(
    repo_full_name: str = Query(..., description="Repository in owner/repo format"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return files with decay status 'decaying' or 'critical'.
    Pulls from stored analysis. Returns 404 if no analysis exists yet.
    """
    normalized_repo = normalize_repo_full_name(repo_full_name)

    result = await db.execute(
        select(RepoAnalysis)
        .where(RepoAnalysis.repo_full_name == normalized_repo)
        .where(RepoAnalysis.user_id == str(user.id))
        .order_by(RepoAnalysis.analyzed_at.desc())
        .limit(1)
    )
    analysis_row = result.scalars().first()

    if analysis_row is None:
        raise RepoNotFoundError(
            f"No analysis found for {normalized_repo}. "
            "Run POST /codeknow/analyze/repo first."
        )

    raw = analysis_row.raw_result or {}
    files_data = raw.get("files", [])

    at_risk_files = []
    for f in files_data:
        decay = f.get("decay")
        if not decay:
            continue
        if decay.get("status") not in ("decaying", "critical"):
            continue
        at_risk_files.append(AtRiskFile(
            path=f["path"],
            decay_status=decay["status"],
            owner=decay["owner"],
            days_since_owner_touched=decay["days_since_owner_touched"],
            commits_since_owner_left=decay["commits_since_owner_left"],
            pct_changed_since_owner_left=decay["pct_changed_since_owner_left"],
        ))

    at_risk_files.sort(key=lambda x: x.pct_changed_since_owner_left, reverse=True)

    return AtRiskResponse(
        repo=normalized_repo,
        analyzed_at=analysis_row.analyzed_at.isoformat(),
        total_at_risk=len(at_risk_files),
        files=at_risk_files,
    )


# --- History endpoint ---

class AnalysisHistoryItem(BaseModel):
    repo_full_name: str
    platform: str
    analyzed_at: str
    total_files: int
    total_at_risk: int
    critical_count: int
    decaying_count: int
    bus_factor_1_count: int


class AnalysisHistoryResponse(BaseModel):
    analyses: list[AnalysisHistoryItem]


def _compute_history_metrics(files_data: list[dict]) -> tuple[int, int, int, int, int]:
    """Derive metrics from raw file analysis data.

    Returns: (total_files, total_at_risk, critical_count, decaying_count, bus_factor_1_count)
    """
    total_files = len(files_data)
    critical_count = 0
    decaying_count = 0
    bus_factor_1_count = 0
    total_at_risk = 0

    for f in files_data:
        decay = f.get("decay")
        if decay:
            status = decay.get("status")
            if status == "critical":
                critical_count += 1
                total_at_risk += 1
            elif status == "decaying":
                decaying_count += 1
                total_at_risk += 1
        bus_factor = f.get("bus_factor", 0) or 0
        if bus_factor == 1:
            bus_factor_1_count += 1

    return total_files, total_at_risk, critical_count, decaying_count, bus_factor_1_count


@router.get("/repo/history", response_model=AnalysisHistoryResponse)
async def get_analysis_history(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all repos the current user has analyzed, most recent first.
    Shows only the latest analysis per repo.
    """
    result = await db.execute(
        select(
            RepoAnalysis.repo_full_name,
            RepoAnalysis.platform,
            RepoAnalysis.analyzed_at,
            RepoAnalysis.raw_result,
        )
        .where(RepoAnalysis.user_id == str(user.id))
        .order_by(RepoAnalysis.analyzed_at.desc())
    )
    rows = result.fetchall()

    seen_repos: dict[str, AnalysisHistoryItem] = {}
    for row in rows:
        repo_name = row.repo_full_name
        if repo_name in seen_repos:
            continue

        files_data = (row.raw_result or {}).get("files", [])
        total_files, total_at_risk, critical_count, decaying_count, bus_factor_1_count = (
            _compute_history_metrics(files_data)
        )

        seen_repos[repo_name] = AnalysisHistoryItem(
            repo_full_name=repo_name,
            platform=row.platform,
            analyzed_at=row.analyzed_at.isoformat(),
            total_files=total_files,
            total_at_risk=total_at_risk,
            critical_count=critical_count,
            decaying_count=decaying_count,
            bus_factor_1_count=bus_factor_1_count,
        )

    return AnalysisHistoryResponse(analyses=list(seen_repos.values()))


# --- Full result endpoint ---

@router.get("/repo/result", response_model=RepoAnalysisResponse)
async def get_stored_result(
    repo_full_name: str = Query(..., description="Repository in owner/repo format"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Fetch the full stored analysis for a repo without re-hitting GitHub."""
    normalized_repo = normalize_repo_full_name(unquote(repo_full_name))

    result = await db.execute(
        select(RepoAnalysis)
        .where(RepoAnalysis.repo_full_name == normalized_repo)
        .where(RepoAnalysis.user_id == str(user.id))
        .order_by(RepoAnalysis.analyzed_at.desc())
        .limit(1)
    )
    analysis_row = result.scalars().first()

    if analysis_row is None:
        raise RepoNotFoundError(
            f"No analysis found for {normalized_repo}. "
            "Run POST /codeknow/analyze/repo first."
        )

    raw = analysis_row.raw_result or {}
    return RepoAnalysisResponse(
        repo=normalized_repo,
        analyzed_at=analysis_row.analyzed_at.isoformat(),
        files=raw.get("files", []),
    )


# --- Modules endpoint ---

class ModuleInfo(BaseModel):
    module_name: str
    total_files: int
    bus_factor_min: int
    bus_factor_avg: float
    critical_files: int
    decaying_files: int
    stable_files: int
    risk_level: str
    top_owners: list[str]


class ModulesResponse(BaseModel):
    repo: str
    analyzed_at: str
    modules: list[ModuleInfo]


def _get_module_name(file_path: str) -> str:
    """Extract top-level folder (module) from a file path."""
    if "/" not in file_path:
        return "(root)"
    return file_path.split("/", 1)[0]


def _compute_modules(files_data: list[dict]) -> list[ModuleInfo]:
    """Roll up file-level data to module level."""
    modules: dict[str, dict] = {}

    for f in files_data:
        file_path = f.get("path", "")
        module_name = _get_module_name(file_path)

        if module_name not in modules:
            modules[module_name] = {
                "files": [],
                "bus_factors": [],
                "owners": [],
            }

        modules[module_name]["files"].append(f)
        modules[module_name]["bus_factors"].append(f.get("bus_factor", 0) or 0)

        for contrib in f.get("contributors", []):
            owner = contrib.get("author", "")
            pct = contrib.get("ownership_pct", 0) or 0
            modules[module_name]["owners"].append((owner, pct))

    result = []
    for module_name, data in modules.items():
        files = data["files"]
        bus_factors = data["bus_factors"]

        critical_files = sum(
            1 for f in files
            if (f.get("decay") or {}).get("status") == "critical"
        )
        decaying_files = sum(
            1 for f in files
            if (f.get("decay") or {}).get("status") == "decaying"
        )
        stable_files = len(files) - critical_files - decaying_files

        bus_factor_min = min(bus_factors) if bus_factors else 0
        bus_factor_avg = round(sum(bus_factors) / len(bus_factors), 1) if bus_factors else 0.0

        # ✅ FIXED: Include solo_developer in critical check
        any_solo_dev = any(
            (f.get("decay") or {}).get("solo_developer") is True
            for f in files
        )

        if bus_factor_min == 1 or critical_files > 0 or any_solo_dev:
            risk_level = "critical"
        elif bus_factor_avg < 2 or decaying_files > 0:
            risk_level = "warning"
        else:
            risk_level = "healthy"

        sorted_owners = sorted(
            data["owners"],
            key=lambda x: x[1],
            reverse=True,
        )
        seen_owners = set()
        top_owners = []
        for owner, pct in sorted_owners:
            if owner not in seen_owners and len(top_owners) < 3:
                top_owners.append(owner)
                seen_owners.add(owner)

        result.append(ModuleInfo(
            module_name=module_name,
            total_files=len(files),
            bus_factor_min=bus_factor_min,
            bus_factor_avg=bus_factor_avg,
            critical_files=critical_files,
            decaying_files=decaying_files,
            stable_files=stable_files,
            risk_level=risk_level,
            top_owners=top_owners,
        ))

    risk_order = {"critical": 0, "warning": 1, "healthy": 2}
    result.sort(key=lambda x: (risk_order.get(x.risk_level, 3), -x.critical_files))

    return result


@router.get("/repo/modules", response_model=ModulesResponse)
async def get_modules(
    repo_full_name: str = Query(..., description="Repository in owner/repo format"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Module-level aggregation — rolls up file-level data to folder level."""
    normalized_repo = normalize_repo_full_name(unquote(repo_full_name))

    result = await db.execute(
        select(RepoAnalysis)
        .where(RepoAnalysis.repo_full_name == normalized_repo)
        .where(RepoAnalysis.user_id == str(user.id))
        .order_by(RepoAnalysis.analyzed_at.desc())
        .limit(1)
    )
    analysis_row = result.scalars().first()

    if analysis_row is None:
        raise RepoNotFoundError(
            f"No analysis found for {normalized_repo}. "
            "Run POST /codeknow/analyze/repo first."
        )

    raw = analysis_row.raw_result or {}
    files_data = raw.get("files", [])

    return ModulesResponse(
        repo=normalized_repo,
        analyzed_at=analysis_row.analyzed_at.isoformat(),
        modules=_compute_modules(files_data),
    )
