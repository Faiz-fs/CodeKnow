"""Pydantic models for the analysis pipeline responses."""

from pydantic import BaseModel


class Contributor(BaseModel):
    author: str
    commits: int
    last_commit: str  # ISO date
    ownership_pct: float


class Decay(BaseModel):
    """Decay detection: signals when original knowledge owners have gone quiet."""
    status: str  # "stable", "decaying", "critical"
    owner: str
    owner_last_commit: str  # ISO date
    days_since_owner_touched: int
    commits_since_owner_left: int
    pct_changed_since_owner_left: float


class FileAnalysis(BaseModel):
    path: str
    contributors: list[Contributor]
    total_commits: int
    bus_factor: int
    decay: Decay | None = None  # None if cannot determine (e.g., single contributor)


class RepoAnalysisResponse(BaseModel):
    repo: str
    analyzed_at: str  # ISO timestamp
    files: list[FileAnalysis]


class AnalyzeRequest(BaseModel):
    repo_url: str  # "owner/repo"
