"""Repository analysis endpoint.

POST /analyze/repo  ->  { repo_url: "owner/repo" }
Runs the GitHub commit pull + contributor-map pipeline and returns the
analysis response shape defined in the product spec.
"""

from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, HTTPException

from app.models.analysis import AnalyzeRequest, RepoAnalysisResponse
from app.services import analysis, github

router = APIRouter()


def _parse_repo(repo_url: str) -> tuple[str, str]:
    """Accept either a full URL or the short `owner/repo` form."""
    repo_url = repo_url.strip().rstrip("/")
    if "github.com" in repo_url:
        # https://github.com/owner/repo(.git)?
        repo_url = repo_url.split("github.com/", 1)[-1]
    repo_url = repo_url.removesuffix(".git")
    parts = repo_url.split("/")
    if len(parts) != 2 or not all(parts):
        raise HTTPException(400, "repo_url must be 'owner/repo' or a GitHub URL")
    return parts[0], parts[1]


@router.post("/repo", response_model=RepoAnalysisResponse)
async def analyze_repo(req: AnalyzeRequest):
    owner, repo = _parse_repo(req.repo_url)
    client = github.GitHubClient()
    try:
        commits = await client.get_commits(owner, repo)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"GitHub API error: {e}") from e
    finally:
        await client.close()

    files = analysis.build_contributor_map(commits)
    return RepoAnalysisResponse(
        repo=f"{owner}/{repo}",
        analyzed_at=datetime.now(timezone.utc).isoformat(),
        files=files,
    )
