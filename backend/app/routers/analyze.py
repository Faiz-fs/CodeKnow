"""Repository analysis endpoint.

POST /codeknow/analyze/repo  ->  { repo_url: "https://github.com/owner/repo" }
Protected by JWT auth. Pulls commit history with per-file detail, builds the
contributor map + bus factor, persists the result, and returns it.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.core.security import decrypt_token
from app.db import get_db
from app.models.analysis import AnalyzeRequest, RepoAnalysisResponse
from app.models.repo_analysis import RepoAnalysis
from app.models.user import User
from app.services import analysis, github

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
