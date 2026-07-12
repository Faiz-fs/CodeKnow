"""Correlation Layer (Engine 3) endpoints.

POST /codeknow/correlation/build?repo_full_name=owner/repo
     — build co-change edges, run Personalized PageRank, store blast radius scores

GET  /codeknow/correlation/blast-radius?repo_full_name=owner/repo&limit=20
     — return ranked blast radius scores with Engine 1 context
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from urllib.parse import unquote
from uuid import uuid4

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.core.errors import RepoNotFoundError
from app.core.repo import normalize_repo_full_name
from app.core.security import decrypt_token
from app.db import get_db
from app.models.graph import GraphEdge, GraphNode, NodeRiskScore
from app.models.repo_analysis import RepoAnalysis
from app.models.user import User
from app.services import correlation as correlation_service
from app.services import github as github_service
from pydantic import BaseModel

router = APIRouter()


# --- Response models ---

class CorrelationBuildResponse(BaseModel):
    repo: str
    co_change_edges_created: int
    nodes_scored: int
    message: str


class BlastRadiusItem(BaseModel):
    file: str
    bus_factor: int
    decay_status: str
    owner: Optional[str] = None
    owner_last_commit_days_ago: Optional[int] = None
    blast_radius_score: float
    downstream_files_affected: int
    risk_tier: str


class BlastRadiusResponse(BaseModel):
    repo: str
    items: list[BlastRadiusItem]


# --- Helpers ---

def _get_repo(repo_full_name: str) -> tuple[str, str]:
    """Parse owner/repo from repo_full_name."""
    normalized = normalize_repo_full_name(repo_full_name)
    parts = normalized.split("/")
    if len(parts) != 2 or not all(parts):
        raise RepoNotFoundError("repo_full_name must be in 'owner/repo' format")
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


def _extract_at_risk_scores(raw_result: dict) -> dict[str, float]:
    """Extract Engine 1 risk scores from stored analysis.

    Returns {file_path: risk_score} where risk_score combines:
    - bus_factor == 1 -> high weight
    - decay status critical/decaying -> weight by severity
    """
    scores: dict[str, float] = {}
    files_data = raw_result.get("files", [])
    for f in files_data:
        path = f.get("path")
        if not path:
            continue

        score = 0.0
        bus_factor = f.get("bus_factor", 0) or 0
        decay = f.get("decay") or {}

        # Bus factor 1 = single point of failure
        if bus_factor == 1:
            score += 1.0

        decay_status = decay.get("status")
        if decay_status == "critical":
            score += 1.0
        elif decay_status == "decaying":
            score += 0.5
        elif decay_status == "warning":
            score += 0.25

        if score > 0:
            scores[path] = score

    return scores


async def _count_downstream_files(
    node_id: str,
    repo_analysis_id: str,
    db: AsyncSession,
    max_depth: int = 2,
) -> int:
    """Count distinct nodes reachable within max_depth hops via outgoing edges."""
    cte_sql = text("""
        WITH RECURSIVE downstream AS (
            SELECT
                gn.id,
                gn.path,
                1 as depth
            FROM graph_edges ge
            JOIN graph_nodes gn ON gn.id = ge.target_node_id
            WHERE ge.source_node_id = :node_id
              AND ge.repo_analysis_id = :analysis_id

            UNION ALL

            SELECT
                gn.id,
                gn.path,
                d.depth + 1
            FROM graph_edges ge
            JOIN graph_nodes gn ON gn.id = ge.target_node_id
            JOIN downstream d ON ge.source_node_id = d.id
            WHERE d.depth < :max_depth
              AND ge.repo_analysis_id = :analysis_id
        )
        SELECT COUNT(DISTINCT path) FROM downstream
    """)

    result = await db.execute(
        cte_sql,
        {"node_id": node_id, "analysis_id": repo_analysis_id, "max_depth": max_depth},
    )
    count = result.scalar() or 0
    return count


# --- Endpoints ---

@router.post("/build", response_model=CorrelationBuildResponse)
async def build_correlation(
    repo_full_name: str = Query(..., description="Repository in owner/repo format"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Build co-change edges, run Personalized PageRank, store blast radius scores.

    1. Fetches existing graph nodes/edges for this analysis
    2. Fetches commit file lists via GitHub client (bounded by CO_CHANGE_MAX_COMMITS)
    3. Computes co-change edges (Jaccard weight >= CO_CHANGE_MIN_WEIGHT)
    4. Persists co-change edges into graph_edges (edge_type='co_changes_with', ON CONFLICT DO NOTHING)
    5. Builds full networkx graph with structural + co-change edges
    6. Pulls Engine 1's bus-factor-1/critical files as risk seed set
    7. Runs compute_blast_radius (Personalized PageRank)
    8. Upserts results into node_risk_scores
    """
    decoded = normalize_repo_full_name(unquote(repo_full_name))
    owner, repo = _get_repo(decoded)

    # Verify analysis belongs to user
    analysis_row = await _get_latest_analysis(decoded, str(user.id), db)

    # 1. Fetch existing graph nodes and edges
    nodes_result = await db.execute(
        select(GraphNode).where(GraphNode.repo_analysis_id == analysis_row.id)
    )
    nodes = nodes_result.scalars().all()

    edges_result = await db.execute(
        select(GraphEdge).where(GraphEdge.repo_analysis_id == analysis_row.id)
    )
    edges = edges_result.scalars().all()

    if not nodes:
        raise RepoNotFoundError(
            f"No graph found for {decoded}. Run POST /codeknow/graph/build first."
        )

    # 2. Fetch commit file lists via GitHub
    if not user.github_access_token_encrypted:
        raise RepoNotFoundError("No GitHub token stored for this user")

    token = decrypt_token(user.github_access_token_encrypted)

    client = github_service.GitHubClient(token=token)
    try:
        commits = await client.fetch_commit_file_lists(owner, repo)
    finally:
        await client.close()

    # 3. Compute co-change edges
    co_change_edges = correlation_service.build_co_change_edges(commits)

    # 4. Persist co-change edges using the same atomic upsert pattern as Engine 2
    now = datetime.now(timezone.utc)
    path_to_node_id = {n.path: n.id for n in nodes if n.node_type == "file"}

    edge_rows: list[dict] = []
    seen_edges: set[tuple[str, str, str]] = set()

    # First, collect existing co-changes_with edges to avoid duplicates (Engine 2 dedup pattern)
    for edge in edges:
        if edge.edge_type == "co_changes_with":
            seen_edges.add((edge.source_node_id, edge.target_node_id, edge.edge_type))

    for cce in co_change_edges:
        source_id = path_to_node_id.get(cce["source"])
        target_id = path_to_node_id.get(cce["target"])
        if not source_id or not target_id:
            continue
        edge_key = (source_id, target_id, "co_changes_with")
        if edge_key in seen_edges:
            continue
        seen_edges.add(edge_key)
        edge_rows.append({
            "id": str(uuid4()),
            "repo_analysis_id": analysis_row.id,
            "source_node_id": source_id,
            "target_node_id": target_id,
            "edge_type": "co_changes_with",
            "weight": cce["weight"],
            "created_at": now,
        })

    if edge_rows:
        # Use the new unique constraint "uq_graph_edges_per_analysis" from migration 0005
        await db.execute(
            pg_insert(GraphEdge.__table__)
            .values(edge_rows)
            .on_conflict_do_nothing(constraint="uq_graph_edges_per_analysis")
        )
        await db.flush()

    # Refresh edges to include new co-change edges
    edges_result = await db.execute(
        select(GraphEdge).where(GraphEdge.repo_analysis_id == analysis_row.id)
    )
    all_edges = edges_result.scalars().all()

    # 5. Build full networkx graph
    G = correlation_service.build_networkx_graph(nodes, all_edges, co_change_edges)

    # 6. Get Engine 1 risk seed set
    at_risk_scores_by_path = _extract_at_risk_scores(analysis_row.raw_result or {})
    # Normalize path for matching: remove leading "./" and lowercase
    def _normalize_path(p: str) -> str:
        if p.startswith("./"):
            p = p[2:]
        return p.lower()
    # Build a normalized map from path to node_id for matching
    path_to_node_id_norm = {_normalize_path(k): v for k, v in path_to_node_id.items()}
    # Map path -> node_id (using normalized path for matching)
    at_risk_scores = {}
    for path, score in at_risk_scores_by_path.items():
        norm_path = _normalize_path(path)
        node_id = path_to_node_id_norm.get(norm_path)
        if node_id is not None:
            at_risk_scores[node_id] = score

    # 7. Run Personalized PageRank
    blast_radius = correlation_service.compute_blast_radius(G, at_risk_scores)

    # 8. Upsert into node_risk_scores
    if blast_radius:
        nr_rows = [
            {
                "id": str(uuid4()),
                "repo_analysis_id": analysis_row.id,
                "node_id": node_id,
                "blast_radius_score": score,
                "computed_at": now,
            }
            for node_id, score in blast_radius.items()
        ]

        await db.execute(
            pg_insert(NodeRiskScore.__table__)
            .values(nr_rows)
            .on_conflict_do_update(
                constraint="uq_node_risk_per_analysis",
                set_={
                    "blast_radius_score": pg_insert(NodeRiskScore.__table__).excluded.blast_radius_score,
                    "computed_at": pg_insert(NodeRiskScore.__table__).excluded.computed_at,
                },
            )
        )
        await db.commit()

    return CorrelationBuildResponse(
        repo=decoded,
        co_change_edges_created=len(edge_rows),
        nodes_scored=len(blast_radius),
        message="Correlation layer built successfully",
    )


@router.get("/blast-radius", response_model=BlastRadiusResponse)
async def get_blast_radius(
    repo_full_name: str = Query(..., description="Repository in owner/repo format"),
    limit: int = Query(default=20, ge=1, le=100, description="Max results to return"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return node_risk_scores joined with graph_nodes and Engine 1 decay data,
    sorted by blast_radius_score descending, limited to `limit`.

    Response shape per item:
    - file: path
    - bus_factor
    - decay_status
    - owner
    - owner_last_commit_days_ago
    - blast_radius_score
    - downstream_files_affected (count of distinct nodes reachable within 2 hops)
    - risk_tier (critical/warning/healthy)
    """
    decoded = normalize_repo_full_name(unquote(repo_full_name))

    analysis_row = await _get_latest_analysis(decoded, str(user.id), db)

    # Join node_risk_scores with graph_nodes
    result = await db.execute(
        select(NodeRiskScore, GraphNode)
        .join(GraphNode, GraphNode.id == NodeRiskScore.node_id)
        .where(NodeRiskScore.repo_analysis_id == analysis_row.id)
        .order_by(NodeRiskScore.blast_radius_score.desc())
        .limit(limit)
    )
    rows = result.fetchall()

    if not rows:
        return BlastRadiusResponse(repo=decoded, items=[])

    # Build Engine 1 lookup by file path (normalize: remove leading "./" and lowercase)
    raw = analysis_row.raw_result or {}
    def _normalize_path(p: str) -> str:
        if p.startswith("./"):
            p = p[2:]
        return p.lower()
    engine1_by_path_norm = {}
    for f in raw.get("files", []):
        path = f.get("path")
        if path:
            norm_path = _normalize_path(path)
            engine1_by_path_norm[norm_path] = {
                "bus_factor": f.get("bus_factor", 0) or 0,
                "decay": f.get("decay") or {},
            }

    items = []
    for nr, node in rows:
        norm_node_path = _normalize_path(node.path)
        e1 = engine1_by_path_norm.get(norm_node_path, {})
        decay = e1.get("decay") or {}

        downstream = await _count_downstream_files(
            node_id=node.id,
            repo_analysis_id=analysis_row.id,
            db=db,
            max_depth=2,
        )

        risk_tier = correlation_service._get_risk_tier(nr.blast_radius_score)

        items.append(BlastRadiusItem(
            file=node.path,
            bus_factor=e1.get("bus_factor", 0),
            decay_status=decay.get("status", "unknown"),
            owner=decay.get("owner"),
            owner_last_commit_days_ago=decay.get("days_since_owner_touched"),
            blast_radius_score=round(nr.blast_radius_score, 6),
            downstream_files_affected=downstream,
            risk_tier=risk_tier,
        ))

    return BlastRadiusResponse(repo=decoded, items=items)