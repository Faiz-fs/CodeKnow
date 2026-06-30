# CodeKnow — Backend

Python + FastAPI service that pulls GitHub commit history and computes the
file→contributor map, ownership %, and bus factor.

## Layout

```
app/
  config.py            # env-driven settings (pydantic-settings)
  main.py              # FastAPI app + CORS + router wiring
  models/analysis.py   # request/response Pydantic models
  services/
    github.py          # async GitHub commits client
    analysis.py        # contributor map + bus factor math
  routers/
    health.py          # GET /health
    auth.py            # GitHub OAuth login (Sprint 1 stub)
    analyze.py         # POST /analyze/repo
```

## Run locally

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate    # macOS/Linux
pip install -r requirements.txt
cp .env.example .env            # fill in secrets
uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000/docs for the interactive API.

## Key endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness check |
| GET | `/auth/github` | Start GitHub OAuth |
| GET | `/auth/github/callback` | OAuth callback |
| POST | `/analyze/repo` | Analyze a repo's contributor map |
