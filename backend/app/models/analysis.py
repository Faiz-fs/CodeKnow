"""Pydantic models for the analysis pipeline responses."""

from pydantic import BaseModel


class Contributor(BaseModel):
    author: str
    commits: int
    last_commit: str  # ISO date
    ownership_pct: float


class FileAnalysis(BaseModel):
    path: str
    contributors: list[Contributor]
    total_commits: int
    bus_factor: int


class RepoAnalysisResponse(BaseModel):
    repo: str
    analyzed_at: str  # ISO timestamp
    files: list[FileAnalysis]


class AnalyzeRequest(BaseModel):
    repo_url: str  # "owner/repo"
