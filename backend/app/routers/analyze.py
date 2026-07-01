"""Repository analysis endpoint.

POST /codeknow/analyze/repo  ->  { repo_url: "https://github.com/owner/repo" }
Protected by JWT auth. Pulls commit history with per-file detail, builds the
contributor map + bus factor, persists the result, and returns it.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.core.security import decrypt_token
from app.db import get_db
from app.models.analysis import AnalyzeRequest, RepoAnalysisResponse
from app.models.repo_analysis import RepoAnalysis
from app.models.user import User
from app.services import analysis, github
from pydantic import BaseModel

router = APIRouter()


def _parse_repo(repo_url: str) -> tuple[str, str]:
    """Parse owner/repo from a full github.com URL or the short form.

    Rejects non-github.com URLs (GitLab support is planned, not here).
    """
    repo_url = repo_url.strip().rstrip("/")
    if "github.com" not in repo_url:
        raise HTTPException(
            400,
            "Only github.com repositories are supported at this time. "
            "Provide a URL like https://github.com/owner/repo.",
        )
    repo_url = repo_url.split("github.com/", 1)[-1].removesuffix(".git")
    parts = repo_url.split("/")
    if len(parts) != 2 or not all(parts):
        raise HTTPException(400, "repo_url must be 'owner/repo' or a github.com URL")
    return parts[0], parts[1]


@router.post("/repo", response_model=RepoAnalysisResponse)
async def analyze_repo(
    req: AnalyzeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    owner, repo = _parse_repo(req.repo_url)

    # Decrypt the user's stored GitHub token for authenticated API calls.
    if not user.github_access_token_encrypted:
        raise HTTPException(400, "No GitHub token stored for this user")
    try:
        token = decrypt_token(user.github_access_token_encrypted)
    except ValueError as e:
        raise HTTPException(500, f"Failed to decrypt stored token: {e}") from e

    client = github.GitHubClient(token=token)
    try:
        commits = await client.get_commits_with_details(owner, repo)
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        if status == 404:
            raise HTTPException(404, f"Repository {owner}/{repo} not found")
        if status == 403:
            raise HTTPException(
                403,
                "GitHub API forbidden — token may lack scope or be rate-limited",
            )
        raise HTTPException(502, f"GitHub API error ({status}): {e}") from e
    except httpx.HTTPError as e:
        raise HTTPException(502, f"GitHub API error: {e}") from e
    finally:
        await client.close()

    files = analysis.build_contributor_map(commits)
    response = RepoAnalysisResponse(
        repo=f"{owner}/{repo}",
        analyzed_at=datetime.now(timezone.utc).isoformat(),
        files=files,
    )

    # Persist the full result.
    record = RepoAnalysis(
        user_id=str(user.id),
        repo_full_name=f"{owner}/{repo}",
        platform="github",
        analyzed_at=datetime.now(timezone.utc),
        raw_result=response.model_dump(mode="json"),
    )
    db.add(record)
    await db.commit()

    return response


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


@router.get("/repo/at-risk", response_model=AtRiskResponse)
async def get_at_risk_files(
    # FIX: query parameter, not path parameter — matches how it's actually called
    repo_full_name: str = Query(..., description="Repository in owner/repo format"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return files with decay status 'decaying' or 'critical'.
    Pulls from stored analysis. Returns 404 if no analysis exists yet.
    """
    if "/" not in repo_full_name:
        raise HTTPException(400, "repo_full_name must be in 'owner/repo' format")

    # FIX: use scalars().first() instead of scalar_one_or_none()
    # to safely handle multiple stored rows for the same repo
    result = await db.execute(
        select(RepoAnalysis)
        .where(RepoAnalysis.repo_full_name == repo_full_name)
        .where(RepoAnalysis.user_id == str(user.id))
        .order_by(RepoAnalysis.analyzed_at.desc())
        .limit(1)
    )
    analysis_row = result.scalars().first()

    if analysis_row is None:
        raise HTTPException(
            404,
            f"No analysis found for {repo_full_name}. "
            "Run POST /codeknow/analyze/repo first.",
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
        repo=repo_full_name,
        analyzed_at=analysis_row.analyzed_at.isoformat(),
        total_at_risk=len(at_risk_files),
        files=at_risk_files,
    )