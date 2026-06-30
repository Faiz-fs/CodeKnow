# CodeKnow — Architecture

## Overview

GitHub repo → commit history → per-file contributor map → bus factor, decay, alerts.

```
┌──────────────┐        ┌──────────────────┐        ┌────────────┐
│  Frontend    │  HTTP  │  Backend (FastAPI)│  API   │  GitHub    │
│  React+Vite  │ ─────▶ │  Python           │ ─────▶ │  REST API  │
│  Vercel      │        │  Render           │        │            │
└──────────────┘        └───────┬──────────┘        └────────────┘
                                │ write/read
                                ▼
                         ┌────────────┐
                         │  Supabase  │
                         │  Postgres  │
                         └─────┬──────┘
                               │ trigger
                               ▼
                         ┌────────────┐
                         │  Resend    │
                         │  email     │
                         └────────────┘
```

## Backend module map

| Module | Responsibility |
|---|---|
| `app/config.py` | Env-driven settings (pydantic-settings) |
| `app/main.py` | FastAPI app, CORS, router wiring |
| `app/models/analysis.py` | Request/response Pydantic models |
| `app/services/github.py` | Async GitHub commits client (paginated) |
| `app/services/analysis.py` | Contributor map builder + bus factor calc |
| `app/routers/health.py` | Liveness check |
| `app/routers/auth.py` | GitHub OAuth login flow |
| `app/routers/analyze.py` | `POST /analyze/repo` |

## Data model (Supabase)

Sprint 1 minimal schema:

```
repos           (id, owner, name, analyzed_at, created_at)
files           (id, repo_id, path)
contributors    (id, file_id, author, commits, last_commit, ownership_pct)
file_snapshots  (id, file_id, total_commits, bus_factor, captured_at)
```

## Bus factor

Bus factor of a file = number of top contributors whose combined ownership
exceeds 50% of commits. A single author owning >50% → bus factor = 1 → red.

## Decay (Sprint 4)

A file is "decaying" when it is still actively committed to, but its top
owner hasn't touched it in 60+ days.

## Environment variables

See `backend/.env.example` and `frontend/.env.example`.
