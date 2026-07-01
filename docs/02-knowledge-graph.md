# Knowledge Graph — Architecture, Plan & Maintenance

**Engine 2 of 3 — CodeKnow**
**Status: BUILD NEXT (after Knowledge Retention System ships, P1.5)**
**Core question answered:** *"What does the codebase look like structurally, and what depends on what?"*

---

## 1. Purpose

Where the Retention System maps **people → code**, the Knowledge Graph maps **code → code**. It builds a structural map of the codebase: which files import which, which functions call which, which API routes exist, which database tables they touch. This is the foundation the Correlation Layer (Engine 3) needs to answer "blast radius" questions like *"if this file breaks, what else breaks?"*

---

## 2. Is This AI-Based or Score-Based?

**Parsing-based, not AI-based.** Extracting "file A imports file B" or "function X calls function Y" is a solved problem with static analysis — no LLM, no training data, no inference cost, fully deterministic, runs in milliseconds per file.

AI only enters later, optionally, as a thin query/explanation layer on top of an already-complete graph (e.g., answering "what breaks if I change the User table?" in natural language). The graph must exist and be correct before that layer makes any sense. See the Codebase Intelligence document for where AI actually fits.

---

## 3. Architecture

```
┌────────────────────────────────────────────────────────┐
│              Knowledge Graph Build Pipeline              │
│                                                            │
│  1. Fetch repo file tree (via GitHub API or shallow clone) │
│  2. Parse each file (language-aware, static analysis)      │
│     - Python: built-in `ast` module                        │
│     - JS/TS: tree-sitter (free, local, multi-language)      │
│  3. Extract:                                                │
│     - imports / requires → file-to-file dependency edges    │
│     - function/class definitions → nodes                    │
│     - API route definitions (FastAPI/Express decorators)    │
│     - DB model definitions (SQLAlchemy/Mongoose classes)    │
│  4. Build graph:                                             │
│     nodes = files, functions, API routes, DB tables          │
│     edges = imports, calls, "route writes to table"          │
│  5. Store in Postgres (adjacency model) — not Neo4j yet      │
└────────────────────────────────────────────────────────┘
```

---

## 4. Storage Model

```sql
nodes (
  id, repo_id, node_type ENUM('file','function','api_route','db_table'),
  name, path, metadata JSONB
)

edges (
  id, repo_id, source_node_id, target_node_id,
  edge_type ENUM('imports','calls','writes_to','reads_from'),
  metadata JSONB
)
```

Recursive CTEs in Postgres can answer "what depends on X, transitively" without needing a dedicated graph database. **Do not introduce Neo4j or another graph DB until a real query proves Postgres genuinely can't handle it.** Adding graph-DB infrastructure before it's needed repeats the exact cloud-complexity trap that stalled earlier projects (Signal/AWS IAM).

---

## 5. Build Order (incremental, each step independently useful)

1. **Python-only parsing first.** Pick whichever language is most common across real test repos and start there — don't build multi-language support before single-language works correctly.
2. **File-to-file import graph only.** Skip function-level call graphs at first — that's a 10x complexity jump for roughly 2x the value. Get "file A imports file B" rock solid before going deeper.
3. **API route + DB table extraction.** Only after the import graph is reliable. This is what makes "what breaks if I change the User table" answerable.
4. **Tech debt markers** (deprecated API still called, circular dependencies). These are graph *queries* against existing data, not new data collection — cheap to add once the graph exists.
5. **tree-sitter / multi-language support.** Add JS/TS (or other languages) once the Python path is proven end-to-end on a real repo.

---

## 6. Why Build This After the Retention System, Not Before

- The Retention System alone is already a complete, demoable product. It doesn't need the graph to deliver value.
- The Knowledge Graph requires meaningfully more engineering (a parser pipeline) than the Retention System (mostly API calls + arithmetic). Building it first risks the "exciting idea, stalls on the hard technical part" pattern from earlier projects.
- The Correlation Layer (Engine 3) — the genuinely differentiated part of the product — cannot exist without both engines already running. There's no shortcut here; this build order is forced by the dependency, not just a priority preference.

---

## 7. Maintenance Plan

- **Re-parsing trigger:** initially on-demand (user clicks "analyze"), same as the Retention System. Webhook-driven re-indexing on every commit (as described in the original product vision) is a Phase 2+ concern — don't build event-driven infrastructure before the on-demand version is validated.
- **Incremental updates:** once webhooks are added later, only re-parse files that changed in a given commit, not the whole repo — full re-parse on every commit will not scale past small repos.
- **Storage growth:** nodes/edges tables will grow linearly with repo size; no special handling needed until a specific repo's graph proves too large for comfortable query times — don't pre-optimize.

---

## 8. What This Engine Deliberately Does NOT Do (Yet)

- No function-level call graph in the first version — file-level import graph only
- No AI-generated explanations — that's an optional layer on top, not part of this engine
- No automatic webhook-driven updates — on-demand analysis only, to start
- No multi-language support until the first language is solid
