"""Authenticated GitHub user-repo listing.

GET /codeknow/github/repos  -> the authenticated user's repositories.

Protected by JWT (get_current_user). Decrypts the user's stored GitHub access
token and calls GitHub's /user/repos, paginating up to MAX_REPOS_TO_FETCH.
"""

from __future__ import annotations

import re
from collections.abc import AsyncGenerator

import httpx
from fastapi import APIRouter, Depends

from app import auth
from app.config import get_settings
from app.core.errors import AuthError, GitHubAPIError, TokenDecryptionError
from app.core.security import decrypt_token
from app.models.github import RepoListResponse, UserRepo
from app.models.user import User

router = APIRouter()

GITHUB_API = "https://api.github.com"
REPOS_PATH = "/user/repos"
PER_PAGE = 100
# Match the `rel="next"` entry in GitHub's Link header, e.g.:
# <https://api.github.com/user/repos?per_page=100&page=2>; rel="next", ...
_LINK_NEXT_RE = re.compile(r'<([^>]+)>;\s*rel="next"')


def _extract_next_link(link_header: str | None) -> str | None:
    """Return the URL for the next page from a GitHub Link header, or None."""
    if not link_header:
        return None
    match = _LINK_NEXT_RE.search(link_header)
    return match.group(1) if match else None


async def _iter_user_repos(token: str) -> AsyncGenerator[dict, None]:
    """Yield raw repo dicts from GitHub's paginated /user/repos.

    Stops when there is no next page, when we've yielded MAX_REPOS_TO_FETCH, or
    when the page returned no repos. Pages are fetched sequentially — repos
    listing is small and latency-bound, not worth concurrent fan-out.
    """
    settings = get_settings()
    limit = settings.max_repos_to_fetch
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "CodeKnow/0.1",
    }

    next_url = (
        f"{GITHUB_API}{REPOS_PATH}"
        f"?per_page={PER_PAGE}&sort=updated&direction=desc"
    )
    yielded = 0

    async with httpx.AsyncClient(timeout=30.0) as client:
        while next_url and yielded < limit:
            resp = await client.get(next_url, headers=headers)

            if resp.status_code == 401:
                raise AuthError(
                    "GitHub token expired or revoked. Please sign in again.",
                )
            if resp.status_code == 403:
                raise GitHubAPIError(
                    "GitHub API forbidden — token may lack the `repo` scope or be "
                    "rate-limited.",
                )

            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                raise GitHubAPIError(
                    f"GitHub API error ({resp.status_code}): {e}",
                ) from e

            page = resp.json()
            if not page:
                break

            for repo in page:
                if yielded >= limit:
                    return
                yield repo
                yielded += 1

            next_url = _extract_next_link(resp.headers.get("link"))


@router.get("/repos", response_model=RepoListResponse)
async def list_repos(user: User = Depends(auth.get_current_user)):
    """Return the authenticated user's repositories (most-recently-updated first)."""
    if not user.github_access_token_encrypted:
        raise AuthError(
            "No GitHub account connected. Please sign in with GitHub first.",
        )

    try:
        token = decrypt_token(user.github_access_token_encrypted)
    except ValueError as e:
        raise TokenDecryptionError(f"Failed to decrypt stored token: {e}") from e

    repos: list[UserRepo] = []
    try:
        async for repo in _iter_user_repos(token):
            repos.append(
                UserRepo(
                    name=repo.get("name") or "",
                    full_name=repo.get("full_name") or "",
                    private=repo.get("private", False),
                    updated_at=repo.get("updated_at") or "",
                    html_url=repo.get("html_url") or "",
                    default_branch=repo.get("default_branch") or "main",
                )
            )
    except (AuthError, GitHubAPIError):
        raise
    except Exception as e:
        raise GitHubAPIError(f"Failed to fetch repos from GitHub: {e}") from e

    return RepoListResponse(repos=repos)
