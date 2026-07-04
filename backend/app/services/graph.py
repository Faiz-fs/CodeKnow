"""Knowledge Graph builder and query service.

Fetches repo file contents via GitHub API, runs the parser on each file,
and persists the resulting nodes + edges to Postgres.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import httpx
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.graph import GraphEdge, GraphNode
from app.services.parser import ParseResult, detect_language, parse_file

GITHUB_API = "https://api.github.com"
# Max files to parse per repo — keeps analysis fast for large repos
MAX_FILES_TO_PARSE = 300
# Concurrent file content fetches
FETCH_CONCURRENCY = 15


async def build_graph(
    owner: str,
    repo: str,
    token: str,
    repo_analysis_id: str,
    db: AsyncSession,
) -> dict:
    """Main entry point. Fetches file tree, parses each file,
    persists nodes + edges, returns a summary."""

    # 1. Get the full file tree from GitHub
    file_paths = await _fetch_file_tree(owner, repo, token)
    file_paths = list(dict.fromkeys(file_paths))

    # 2. Filter to supported languages only
    parseable = [p for p in file_paths if detect_language(p) is not None]
    parseable = parseable[:MAX_FILES_TO_PARSE]

    # 3. Fetch file contents concurrently and parse
    parse_results = await _fetch_and_parse_all(owner, repo, token, parseable)

    # 4. Delete any existing graph for this analysis (re-build on re-analyze)
    await db.execute(
        delete(GraphNode).where(GraphNode.repo_analysis_id == repo_analysis_id)
    )
    await db.flush()

    # 5. Build deduped node rows keyed by (node_type, path)
    now = datetime.now(timezone.utc)
    nodes_by_key: dict[tuple[str, str], dict] = {}
    path_to_node_id: dict[str, str] = {}

    for result in parse_results:
        file_path = result.file_path

        file_key = ("file", file_path)
        if file_key not in nodes_by_key:
            node_id = str(uuid4())
            nodes_by_key[file_key] = {
                "id": node_id,
                "repo_analysis_id": repo_analysis_id,
                "node_type": "file",
                "name": file_path.split("/")[-1],
                "path": file_path,
                "created_at": now,
            }
            path_to_node_id[file_path] = node_id

        for route in result.api_routes:
            route_path = f"{file_path}#{route}"
            route_key = ("api_route", route_path)
            if route_key not in nodes_by_key:
                nodes_by_key[route_key] = {
                    "id": str(uuid4()),
                    "repo_analysis_id": repo_analysis_id,
                    "node_type": "api_route",
                    "name": route,
                    "path": route_path,
                    "created_at": now,
                }

        for table in result.db_tables:
            table_path = f"{file_path}#{table}"
            table_key = ("db_table", table_path)
            if table_key not in nodes_by_key:
                nodes_by_key[table_key] = {
                    "id": str(uuid4()),
                    "repo_analysis_id": repo_analysis_id,
                    "node_type": "db_table",
                    "name": table,
                    "path": table_path,
                    "created_at": now,
                }

    if nodes_by_key:
        await db.execute(
            pg_insert(GraphNode.__table__)
            .values(list(nodes_by_key.values()))
            .on_conflict_do_nothing(constraint="uq_node_per_analysis")
        )
    await db.flush()

    # 6. Persist edges (import relationships between files)
    edge_rows: list[dict] = []
    seen_edges: set[tuple[str, str, str]] = set()
    for result in parse_results:
        source_id = path_to_node_id.get(result.file_path)
        if not source_id:
            continue

        for imported_path in result.imports:
            target_id = _resolve_import(imported_path, result.file_path, path_to_node_id)
            if not target_id or target_id == source_id:
                continue
            edge_key = (source_id, target_id, "imports")
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)
            edge_rows.append({
                "id": str(uuid4()),
                "repo_analysis_id": repo_analysis_id,
                "source_node_id": source_id,
                "target_node_id": target_id,
                "edge_type": "imports",
                "created_at": now,
            })

    if edge_rows:
        await db.execute(pg_insert(GraphEdge.__table__).values(edge_rows))

    await db.commit()

    # 7. Return summary
    file_count = len([r for r in parse_results if r.error is None])
    error_count = len([r for r in parse_results if r.error is not None])
    route_count = sum(len(r.api_routes) for r in parse_results)
    table_count = sum(len(r.db_tables) for r in parse_results)

    return {
        "files_parsed": file_count,
        "files_failed": error_count,
        "edges_created": len(edge_rows),
        "api_routes_found": route_count,
        "db_tables_found": table_count,
        "total_nodes": len(nodes_by_key),
    }


async def get_graph_summary(repo_analysis_id: str, db: AsyncSession) -> dict | None:
    """Return a summary of the stored graph for a repo analysis."""
    result = await db.execute(
        select(GraphNode).where(GraphNode.repo_analysis_id == repo_analysis_id)
    )
    nodes = result.scalars().all()
    if not nodes:
        return None

    edges_result = await db.execute(
        select(GraphEdge).where(GraphEdge.repo_analysis_id == repo_analysis_id)
    )
    edges = edges_result.scalars().all()

    files = [n for n in nodes if n.node_type == "file"]
    routes = [n for n in nodes if n.node_type == "api_route"]
    tables = [n for n in nodes if n.node_type == "db_table"]

    return {
        "total_nodes": len(nodes),
        "file_nodes": len(files),
        "api_route_nodes": len(routes),
        "db_table_nodes": len(tables),
        "total_edges": len(edges),
        "files": [{"path": n.path, "name": n.name} for n in files],
        "api_routes": [{"path": n.path, "route": n.name} for n in routes],
        "db_tables": [{"path": n.path, "table": n.name} for n in tables],
    }


async def get_dependents(
    file_path: str,
    repo_analysis_id: str,
    db: AsyncSession,
    max_depth: int = 3,
) -> dict:
    """Return all files that import the given file, up to max_depth levels deep.
    Uses recursive CTE in Postgres — no graph DB needed."""

    # First find the node id for this file
    result = await db.execute(
        select(GraphNode).where(
            GraphNode.repo_analysis_id == repo_analysis_id,
            GraphNode.path == file_path,
            GraphNode.node_type == "file",
        )
    )
    node = result.scalars().first()
    if not node:
        return {"file_path": file_path, "direct_dependents": [], "transitive_dependents": [], "total": 0}

    # Recursive CTE: traverse edges INWARD (who imports this file?)
    cte_sql = text("""
        WITH RECURSIVE dependents AS (
            SELECT
                gn.id,
                gn.path,
                gn.name,
                1 as depth
            FROM graph_edges ge
            JOIN graph_nodes gn ON gn.id = ge.source_node_id
            WHERE ge.target_node_id = :node_id
              AND ge.repo_analysis_id = :analysis_id

            UNION ALL

            SELECT
                gn.id,
                gn.path,
                gn.name,
                d.depth + 1
            FROM graph_edges ge
            JOIN graph_nodes gn ON gn.id = ge.source_node_id
            JOIN dependents d ON ge.target_node_id = d.id
            WHERE d.depth < :max_depth
              AND ge.repo_analysis_id = :analysis_id
        )
        SELECT DISTINCT path, name, MIN(depth) as depth
        FROM dependents
        GROUP BY path, name
        ORDER BY depth, path
    """)

    rows = await db.execute(
        cte_sql,
        {"node_id": node.id, "analysis_id": repo_analysis_id, "max_depth": max_depth},
    )
    all_dependents = rows.fetchall()

    direct = [{"path": r.path, "name": r.name} for r in all_dependents if r.depth == 1]
    transitive = [{"path": r.path, "name": r.name} for r in all_dependents if r.depth > 1]

    return {
        "file_path": file_path,
        "direct_dependents": direct,
        "transitive_dependents": transitive,
        "total": len(all_dependents),
    }


# --- GitHub file fetching helpers ---

async def _fetch_file_tree(owner: str, repo: str, token: str) -> list[str]:
    """Fetch the full file tree for the default branch using Git Trees API."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "CodeKnow/0.1",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Get default branch
        repo_resp = await client.get(
            f"{GITHUB_API}/repos/{owner}/{repo}",
            headers=headers,
        )
        repo_resp.raise_for_status()
        default_branch = repo_resp.json().get("default_branch", "main")

        # Get recursive tree
        tree_resp = await client.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/git/trees/{default_branch}",
            headers=headers,
            params={"recursive": "1"},
        )
        tree_resp.raise_for_status()
        tree = tree_resp.json()

    return [
        item["path"]
        for item in tree.get("tree", [])
        if item.get("type") == "blob"
    ]


async def _fetch_file_content(
    owner: str,
    repo: str,
    path: str,
    token: str,
    client: httpx.AsyncClient,
) -> str | None:
    """Fetch raw file content from GitHub."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.raw+json",
        "User-Agent": "CodeKnow/0.1",
    }
    try:
        resp = await client.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}",
            headers=headers,
        )
        if resp.status_code == 200:
            # GitHub returns raw content when Accept is raw+json
            return resp.text
    except Exception:
        pass
    return None


async def _fetch_and_parse_all(
    owner: str,
    repo: str,
    token: str,
    file_paths: list[str],
) -> list[ParseResult]:
    """Fetch and parse all files concurrently with a semaphore."""
    semaphore = asyncio.Semaphore(FETCH_CONCURRENCY)

    async def _fetch_one(path: str) -> ParseResult:
        async with semaphore:
            async with httpx.AsyncClient(timeout=20.0) as client:
                content = await _fetch_file_content(owner, repo, path, token, client)
            if content is None:
                return ParseResult(file_path=path, language="unknown", error="Failed to fetch")
            return parse_file(path, content)

    return await asyncio.gather(*(_fetch_one(p) for p in file_paths))


def _resolve_import(
    imported: str,
    source_file: str,
    path_to_node_id: dict[str, str],
) -> str | None:
    """Try to match an import string to an actual file node in the repo.

    Tries several path variations to handle missing extensions,
    index files, and partial module paths.
    """
    source_dir = "/".join(source_file.split("/")[:-1])

    candidates = [
        imported,
        f"{imported}.py",
        f"{imported}.js",
        f"{imported}.ts",
        f"{imported}/index.js",
        f"{imported}/index.ts",
        f"{imported}/__init__.py",
        f"{source_dir}/{imported}",
        f"{source_dir}/{imported}.py",
        f"{source_dir}/{imported}.js",
        f"{source_dir}/{imported}.ts",
    ]

    for candidate in candidates:
        # Normalize path (remove ./ prefix, resolve ../)
        normalized = _normalize_path(candidate)
        if normalized in path_to_node_id:
            return path_to_node_id[normalized]

    return None


def _normalize_path(path: str) -> str:
    """Normalize a path: remove leading ./, resolve ../."""
    parts = []
    for part in path.replace("\\", "/").split("/"):
        if part == "..":
            if parts:
                parts.pop()
        elif part not in (".", ""):
            parts.append(part)
    return "/".join(parts)
