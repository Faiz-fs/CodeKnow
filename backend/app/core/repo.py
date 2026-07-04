"""GitHub repository name parsing and normalization."""

from __future__ import annotations

from app.core.errors import InvalidRepoURLError


def normalize_repo_full_name(value: str) -> str:
    """Normalize an owner/repo string to lowercase for consistent storage and lookup."""
    value = value.strip().rstrip("/")
    if "/" not in value:
        raise InvalidRepoURLError("repo_full_name must be in 'owner/repo' format")
    parts = value.split("/")
    if len(parts) != 2 or not all(parts):
        raise InvalidRepoURLError("repo_full_name must be in 'owner/repo' format")
    return f"{parts[0].lower()}/{parts[1].lower()}"


def parse_repo_url(repo_url: str) -> tuple[str, str]:
    """Parse a full github.com URL or owner/repo short form into (owner, repo), lowercased.

    Rejects non-github.com URLs (GitLab support is planned, not here).
    """
    repo_url = repo_url.strip().rstrip("/")
    if "github.com" not in repo_url:
        raise InvalidRepoURLError(
            "Only github.com repositories are supported at this time. "
            "Provide a URL like https://github.com/owner/repo."
        )
    repo_url = repo_url.split("github.com/", 1)[-1].removesuffix(".git")
    parts = repo_url.split("/")
    if len(parts) != 2 or not all(parts):
        raise InvalidRepoURLError("repo_url must be 'owner/repo' or a github.com URL")
    return parts[0].lower(), parts[1].lower()
