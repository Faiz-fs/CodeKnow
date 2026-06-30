"""GitHub API client for pulling commit history per repository."""

from __future__ import annotations

import httpx

GITHUB_API = "https://api.github.com"


class GitHubClient:
    """Minimal async client for the GitHub commits endpoint.

    Commits are paginated (max 100/page). We walk pages until either the
    commit count limit or the hard page cap is hit, to keep analysis bounded
    for very large repos.
    """

    def __init__(self, token: str | None = None, per_page: int = 100,
                 max_pages: int = 20):
        headers = {"Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.client = httpx.AsyncClient(base_url=GITHUB_API, headers=headers,
                                        timeout=30.0)
        self.per_page = per_page
        self.max_pages = max_pages

    async def get_commits(self, owner: str, repo: str) -> list[dict]:
        """Return raw commit objects with author + date, newest first."""
        commits: list[dict] = []
        for page in range(1, self.max_pages + 1):
            resp = await self.client.get(
                f"/repos/{owner}/{repo}/commits",
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

    async def close(self):
        await self.client.aclose()
