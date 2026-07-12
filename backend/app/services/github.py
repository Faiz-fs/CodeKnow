"""GitHub API client: OAuth exchange, profile fetch, commit history + per-file detail."""

from __future__ import annotations

import asyncio

import httpx

from app.config import get_settings

GITHUB_API = "https://api.github.com"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"

# When remaining requests drop below this, pause to avoid exhausting the limit.
RATE_LIMIT_LOW_WATER = 10
RATE_LIMIT_BACKOFF_SECONDS = 2.0


class GitHubClient:
    """Async GitHub client for authenticated analysis calls."""

    def __init__(self, token: str | None = None, per_page: int = 100,
                 max_pages: int = 20):
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "CodeKnow/0.1",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.client = httpx.AsyncClient(base_url=GITHUB_API, headers=headers,
                                        timeout=30.0)
        self.per_page = per_page
        self.max_pages = max_pages
        self._last_response: httpx.Response | None = None

    # --- Commit history ---
    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        """Wrap client calls so we always capture the latest response for
        rate-limit inspection."""
        resp = await self.client.request(method, path, **kwargs)
        self._last_response = resp
        return resp

    async def get_commits(self, owner: str, repo: str) -> list[dict]:
        """Return raw commit objects (sha, author, date), newest first."""
        commits: list[dict] = []
        for page in range(1, self.max_pages + 1):
            resp = await self._request(
                "GET", f"/repos/{owner}/{repo}/commits",
                params={"per_page": self.per_page, "page": page},
            )
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            commits.extend(batch)
            if len(batch) < self.per_page:
                break
        return commits

    async def get_commit_detail(self, owner: str, repo: str, sha: str) -> dict:
        """Return a single commit's detail, including its `files` array."""
        resp = await self._request("GET", f"/repos/{owner}/{repo}/commits/{sha}")
        resp.raise_for_status()
        return resp.json()

    async def get_commits_with_details(self, owner: str, repo: str) -> list[dict]:
        """Fetch the commit list, then concurrently fetch each commit's detail
        (with its `files` list). Honors rate-limit headers and caps concurrency.

        Returns commits enriched with their `files` list, capped at
        MAX_COMMITS_TO_ANALYZE.
        """
        settings = get_settings()
        commits = await self.get_commits(owner, repo)
        commits = commits[: settings.max_commits_to_analyze]

        semaphore = asyncio.Semaphore(settings.github_concurrent_requests)

        async def _fetch(c: dict) -> dict:
            async with semaphore:
                sha = c.get("sha")
                if not sha:
                    return c
                try:
                    detail = await self.get_commit_detail(owner, repo, sha)
                except httpx.HTTPError:
                    # If a single detail call fails, fall back to the list entry.
                    return c
                # Merge the detail's `files` into the list entry.
                c = dict(c)
                c["files"] = detail.get("files") or []
                await self._maybe_backoff()
                return c

        return await asyncio.gather(*(_fetch(c) for c in commits))

    async def _maybe_backoff(self) -> None:
        """If the last response indicated we're near the rate limit, sleep."""
        last = self._last_response
        if last is None:
            return
        remaining = last.headers.get("X-RateLimit-Remaining")
        if remaining is not None and int(remaining) < RATE_LIMIT_LOW_WATER:
            await asyncio.sleep(RATE_LIMIT_BACKOFF_SECONDS)

    async def fetch_commit_file_lists(self, owner: str, repo: str,
                                      max_commits: int | None = None) -> list[dict]:
        """Return a compact list of commits with only sha and files_changed paths.

        Each item: {"sha": str, "files_changed": [path, ...]}.

        One GitHub API call per commit (to /commits/{sha}), so max_commits is
        a hard cap (default from config) to avoid exhausting the rate limit.
        """
        settings = get_settings()
        max_c = max_commits or settings.co_change_max_commits
        commits = await self.get_commits(owner, repo)
        commits = commits[:max_c]

        semaphore = asyncio.Semaphore(settings.github_concurrent_requests)

        async def _fetch_files(c: dict) -> dict:
            async with semaphore:
                sha = c.get("sha")
                if not sha:
                    return {"sha": "", "files_changed": []}
                try:
                    detail = await self.get_commit_detail(owner, repo, sha)
                except httpx.HTTPError:
                    return {"sha": sha, "files_changed": []}
                files = [f.get("filename") for f in (detail.get("files") or []) if f.get("filename")]
                await self._maybe_backoff()
                return {"sha": sha, "files_changed": files}

        return await asyncio.gather(*(_fetch_files(c) for c in commits))

    async def close(self) -> None:
        await self.client.aclose()


# --- OAuth helpers (synchronous, used in the auth router) ---

def exchange_code_for_token(code: str) -> str:
    """Exchange an OAuth code for a GitHub access token. Returns the token."""
    settings = get_settings()
    resp = httpx.post(
        GITHUB_TOKEN_URL,
        headers={"Accept": "application/json"},
        data={
            "client_id": settings.github_client_id,
            "client_secret": settings.github_client_secret,
            "code": code,
            "redirect_uri": settings.github_redirect_uri,
        },
        timeout=15.0,
    )
    resp.raise_for_status()
    token = resp.json().get("access_token")
    if not token:
        raise ValueError(f"GitHub token exchange failed: {resp.text}")
    return token


def fetch_user_profile(token: str) -> dict:
    """Fetch the authenticated GitHub user's profile."""
    resp = httpx.get(
        f"{GITHUB_API}/user",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "CodeKnow/0.1",
        },
        timeout=15.0,
    )
    resp.raise_for_status()
    return resp.json()
