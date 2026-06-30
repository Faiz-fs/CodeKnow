"""Pydantic models for the GitHub repo-listing response."""

from __future__ import annotations

from pydantic import BaseModel


class UserRepo(BaseModel):
    name: str
    full_name: str
    private: bool
    updated_at: str  # ISO 8601, e.g. "2026-06-20T10:00:00Z"
    html_url: str
    default_branch: str


class RepoListResponse(BaseModel):
    repos: list[UserRepo]
