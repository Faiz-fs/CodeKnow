"""Correlation Layer (Engine 3): co-change edges + Personalized PageRank blast radius."""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

import networkx as nx

from app.config import get_settings

if TYPE_CHECKING:
    from app.models.graph import GraphEdge, GraphNode


def build_co_change_edges(
    commits: list[dict],
    min_weight: float | None = None,
) -> list[dict]:
    """Compute pairwise co-occurrence weight per file pair using Jaccard-style weighting.

    Args:
        commits: List of {"sha": str, "files_changed": [path, ...]}
        min_weight: Minimum Jaccard weight to keep an edge. Default from config.

    Returns:
        List of {"source": path_a, "target": path_b, "weight": float, "edge_type": "co_changes_with"}
        Only pairs with weight >= min_weight are included.
    """
    settings = get_settings()
    if min_weight is None:
        min_weight = settings.co_change_min_weight

    # Count individual file occurrences
    file_counts: dict[str, int] = defaultdict(int)
    # Count co-occurrences: (file_a, file_b) -> count
    co_counts: dict[tuple[str, str], int] = defaultdict(int)

    for commit in commits:
        files = commit.get("files_changed") or []
        if len(files) < 2:
            continue
        # Sort for consistent tuple keys
        sorted_files = sorted(files)
        for i, f1 in enumerate(sorted_files):
            file_counts[f1] += 1
            for f2 in sorted_files[i + 1:]:
                file_counts[f2] += 1
                key = (f1, f2)
                co_counts[key] += 1

    # Build edges with Jaccarddaccard weight = co_count / (count_a + count_b - co_count)
    edges: list[dict] = []
    for (f1, f2), co_count in co_counts.items():
        count_a = file_counts[f1]
        count_b = file_counts[f2]
        weight = co_count / (count_a + count_b - co_count)
        if weight >= min_weight:
            edges.append({
                "source": f1,
                "target": f2,
                "weight": weight,
                "edge_type": "co_changes_with",
            })

    return edges


def build_networkx_graph(
    nodes: list["GraphNode"],
    edges: list["GraphEdge"],
    co_change_edges: list[dict],
) -> nx.DiGraph:
    """Build a networkx.DiGraph from graph nodes/edges plus co-change edges.

    Applies edge_type_weight_multiplier from config to each edge's weight.
    """
    settings = get_settings()
    multipliers = settings.edge_type_weight_multiplier

    G = nx.DiGraph()

    # Add nodes
    for node in nodes:
        G.add_node(node.id, path=node.path, name=node.name, node_type=node.node_type)

    # Add structural edges (imports, calls, etc.)
    for edge in edges:
        multiplier = multipliers.get(edge.edge_type, 1.0)
        weight = edge.weight * multiplier
        G.add_edge(
            edge.source_node_id,
            edge.target_node_id,
            weight=weight,
            edge_type=edge.edge_type,
        )

    # Build path->node_id map for co-change edges
    path_to_node_id = {node.path: node.id for node in nodes if node.node_type == "file"}

    # Add co-change edges (undirected -> add both directions)
    for cce in co_change_edges:
        source_id = path_to_node_id.get(cce["source"])
        target_id = path_to_node_id.get(cce["target"])
        if not source_id or not target_id:
            continue
        multiplier = multipliers.get("co_changes_with", 1.0)
        weight = cce["weight"] * multiplier
        G.add_edge(source_id, target_id, weight=weight, edge_type="co_changes_with")
        G.add_edge(target_id, source_id, weight=weight, edge_type="co_changes_with")

    return G


def compute_blast_radius(
    G: nx.DiGraph,
    at_risk_scores: dict[str, float],
    damping: float | None = None,
) -> dict[str, float]:
    """Run Personalized PageRank with at_risk_scores as personalization vector.

    Args:
        G: networkx DiGraph with 'weight' edge attribute.
        at_risk_scores: {node_id: risk_score} — Engine 1's bus-factor-1 / critical
            decay files, weighted by their existing risk severity.
        damping: PageRank damping factor. Default from config (PPR_DAMPING_FACTOR).

    Returns:
        {node_id: blast_radius_score} — PPR scores for all nodes in the graph.
    """
    settings = get_settings()
    if damping is None:
        damping = settings.ppr_damping_factor

    if not at_risk_scores:
        # No personalization -> uniform PageRank
        return nx.pagerank(G, weight="weight", alpha=damping)

    # Normalize personalization to sum to 1 (networkx requirement)
    total = sum(at_risk_scores.values())
    if total > 0:
        personalization = {k: v / total for k, v in at_risk_scores.items()}
    else:
        personalization = at_risk_scores

    # Only include nodes that exist in the graph
    personalization = {k: v for k, v in personalization.items() if k in G}

    # DEBUG: Print personalization (what will be passed to pagerank)
    print(f"DEBUG: personalization (for pagerank) length: {len(personalization)}")
    if personalization:
        print(f"DEBUG: sample of personalization: {list(personalization.items())[:5]}")
    else:
        print("DEBUG: personalization is empty -> will use uniform pagerank")

    if not personalization:
        return nx.pagerank(G, weight="weight", alpha=damping)

    return nx.pagerank(G, weight="weight", alpha=damping, personalization=personalization)


def _get_risk_tier(score: float) -> str:
    """Determine risk tier from blast radius score.

    Buckets (configurable via settings later):
    - critical: top 10% or score > 0.05
    - warning: top 25% or score > 0.01
    - healthy: rest
    """
    # These are initial reasonable defaults; can be made configurable
    if score > 0.05:
        return "critical"
    elif score > 0.01:
        return "warning"
    return "healthy"