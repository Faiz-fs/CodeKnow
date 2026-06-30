# CodeKnow — Backend

Python + FastAPI service that pulls GitHub commit history and computes the
file→contributor map, ownership %, and bus factor. Results are persisted to
Postgres; users authenticate via GitHub OAuth and call the API with a JWT.

## Layout

```
app/
  config.py              # env-driven settings (pydantic-settings)
  main.py                # FastAPI app + CORS + router wiring
  auth.py                # JWT get_current_user dependency
  db.py                  # async SQLAlchemy engine + get_db dependency
  core/
    security.py          # Fernet token encrypt/decrypt, JWT, OAuth state signing
  models/
    analysis.py          # request/response Pydantic models
    user.py              # users ORM model
    repo_analysis.py     # repo_analyses ORM model
  services/
    github.py            # async GitHub client (commits, detail, OAuth exchange)
    analysis.py          # contributor map + bus factor math
  routers/
    health.py            # GET /health
    auth.py              # GET /auth/github/login, /auth/github/callback
    analyze.py           # POST /analyze/repo (JWT-protected)
alembic/                 # migrations
```

## Local setup

### 1. Create the local database

Make sure Postgres is running, then create the database:

```bash
# via psql
psql -U postgres -c "CREATE DATABASE codeknow_db;"
```

### 2. Install + configure

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate    # macOS/Linux
pip install -r requirements.txt
cp .env.example .env            # fill in secrets
```

Fill in `.env`:

- `DATABASE_URL` — defaults to `postgresql+asyncpg://postgres:postgres@localhost:5432/codeknow_db`
- `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` — from a GitHub OAuth App
- `GITHUB_REDIRECT_URI` — must be `http://localhost:8080/codeknow/auth/github/callback`
  (register this exact callback in your GitHub OAuth App settings)
- `JWT_SECRET` — `openssl rand -hex 32`
- `ENCRYPTION_KEY` — `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
- `FRONTEND_REDIRECT` — optional; set to your frontend URL for browser redirect flow

### 3. Run migrations

```bash
alembic upgrade head
```

This creates the `users` and `repo_analyses` tables.

### 4. Run the server

```bash
uvicorn app.main:app --reload --port 8080
```

Open http://localhost:8080/docs for the interactive API.

## Key endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/codeknow/health` | Liveness check |
| GET | `/codeknow/auth/github/login` | Redirect to GitHub OAuth |
| GET | `/codeknow/auth/github/callback` | OAuth callback → JWT |
| POST | `/codeknow/analyze/repo` | Analyze a repo (JWT-protected) |

## Notes

- The analyze endpoint fetches the most recent `MAX_COMMITS_TO_ANALYZE` commits
  (default 500), then concurrently fetches each commit's detail (its `files`
  array) with up to `GITHUB_CONCURRENT_REQUESTS` (default 10) in flight.
- GitHub rate limits are honored via `X-RateLimit-Remaining`; the client
  pauses when the remaining quota runs low.
- Switching to Supabase later is just a `DATABASE_URL` change — the code uses
  standard Postgres via SQLAlchemy, nothing Supabase-specific.
