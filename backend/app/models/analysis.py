"""Pydantic models for the analysis pipeline responses."""

from pydantic import BaseModel


class Contributor(BaseModel):
    author: str
    commits: int
    last_commit: str  # ISO date
    ownership_pct: float


class Decay(BaseModel):
    status: str
    owner: str
    owner_last_commit: str
    days_since_owner_touched: int
    commits_since_owner_left: int
    pct_changed_since_owner_left: float
    solo_developer: bool | None = None


class FileAnalysis(BaseModel):
    path: str
    contributors: list[Contributor]
    total_commits: int
    bus_factor: int
    decay: Decay | None = None


class RepoAnalysisResponse(BaseModel):
    repo: str
    analyzed_at: str
    files: list[FileAnalysis]
    total_contributors: int = 0           # ✅ Default for backward compatibility
    solo_developer_repo: bool = False     # ✅ Default for backward compatibility
    config_used: dict = {}                # ✅ Default for backward compatibility


class AnalyzeRequest(BaseModel):
    repo_url: str