"""Knowledge Graph endpoints.

POST /codeknow/graph/build?repo_full_name=owner/repo
     — parse repo files, build and persist the graph

GET  /codeknow/graph/summary?repo_full_name=owner/repo
     — return graph summary (node/edge counts, file list, routes, tables)

GET  /codeknow/graph/dependents?repo_full_name=owner/repo&file_path=src/foo.py
     — return all files that import the given file (blast radius)
"""

from __future__ import annotations

from urllib.parse import unquote

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.core.errors import (
    GitHubAPIError,
    InvalidRepoURLError,
    RepoNotFoundError,
    TokenDecryptionError,
)
from app.core.repo import normalize_repo_full_name
from app.core.security import decrypt_token
from app.db import get_db
from app.models.repo_analysis import RepoAnalysis
from app.models.user import User
from app.services import graph as graph_service
from pydantic import BaseModel

router = APIRouter()


def _get_repo(repo_full_name: str) -> tuple[str, str]:
    normalized = normalize_repo_full_name(repo_full_name)
    parts = normalized.split("/")
    if len(parts) != 2 or not all(parts):
        raise InvalidRepoURLError("repo_full_name must be in 'owner/repo' format")
    return parts[0], parts[1]


async def _get_latest_analysis(
    repo_full_name: str,
    user_id: str,
    db: AsyncSession,
) -> RepoAnalysis:
    result = await db.execute(
        select(RepoAnalysis)
        .where(RepoAnalysis.repo_full_name == repo_full_name)
        .where(RepoAnalysis.user_id == user_id)
        .order_by(RepoAnalysis.analyzed_at.desc())
        .limit(1)
    )
    row = result.scalars().first()
    if row is None:
        raise RepoNotFoundError(
            f"No analysis found for {repo_full_name}. "
            "Run POST /codeknow/analyze/repo first."
        )
    return row


# --- Response models ---

class GraphBuildResponse(BaseModel):
    repo: str
    files_parsed: int
    files_failed: int
    edges_created: int
    api_routes_found: int
    db_tables_found: int
    total_nodes: int


class GraphSummaryResponse(BaseModel):
    repo: str
    total_nodes: int
    file_nodes: int
    api_route_nodes: int
    db_table_nodes: int
    total_edges: int
    files: list[dict]
    api_routes: list[dict]
    db_tables: list[dict]


class DependentsResponse(BaseModel):
    repo: str
    file_path: str
    direct_dependents: list[dict]
    transitive_dependents: list[dict]
    total: int


# --- Endpoints ---

@router.post("/build", response_model=GraphBuildResponse)
async def build_graph(
    repo_full_name: str = Query(..., description="Repository in owner/repo format"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Parse repo file contents and build the knowledge graph.
    Requires an existing analysis (run POST /analyze/repo first).
    Re-running replaces the previous graph for this analysis.
    """
    decoded = normalize_repo_full_name(unquote(repo_full_name))
    owner, repo = _get_repo(decoded)

    # Get the stored analysis to link the graph to
    analysis_row = await _get_latest_analysis(decoded, str(user.id), db)

    # Decrypt the user's GitHub token
    if not user.github_access_token_encrypted:
        raise TokenDecryptionError("No GitHub token stored for this user")
    try:
        token = decrypt_token(user.github_access_token_encrypted)
    except ValueError as e:
        raise TokenDecryptionError(f"Failed to decrypt stored token: {e}") from e

    try:
        summary = await graph_service.build_graph(
            owner=owner,
            repo=repo,
            token=token,
            repo_analysis_id=analysis_row.id,
            db=db,
        )
    except Exception as e:
        raise GitHubAPIError(f"Graph build failed: {e}") from e

    return GraphBuildResponse(repo=decoded, **summary)


@router.get("/summary", response_model=GraphSummaryResponse)
async def get_graph_summary(
    repo_full_name: str = Query(..., description="Repository in owner/repo format"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the stored knowledge graph summary for a repo."""
    decoded = normalize_repo_full_name(unquote(repo_full_name))
    analysis_row = await _get_latest_analysis(decoded, str(user.id), db)

    summary = await graph_service.get_graph_summary(analysis_row.id, db)
    if summary is None:
        raise RepoNotFoundError(
            f"No graph found for {decoded}. Run POST /codeknow/graph/build first."
        )

    return GraphSummaryResponse(repo=decoded, **summary)


@router.get("/dependents", response_model=DependentsResponse)
async def get_dependents(
    repo_full_name: str = Query(..., description="Repository in owner/repo format"),
    file_path: str = Query(..., description="File path to check dependents for, e.g. src/auth.py"),
    depth: int = Query(default=3, ge=1, le=5, description="Max traversal depth"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all files that import the given file (blast radius).
    Uses recursive graph traversal up to the specified depth.
    """
    decoded = normalize_repo_full_name(unquote(repo_full_name))
    analysis_row = await _get_latest_analysis(decoded, str(user.id), db)

    result = await graph_service.get_dependents(
        file_path=file_path,
        repo_analysis_id=analysis_row.id,
        db=db,
        max_depth=depth,
    )

    return DependentsResponse(repo=decoded, **result)
