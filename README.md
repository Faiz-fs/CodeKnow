# CodeKnow

Codebase intelligence & knowledge-retention platform for engineering teams.
Analyzes a GitHub repo's commit history to surface knowledge-concentration
risk: who owns what, what happens if they leave (bus factor), and where
institutional knowledge is drifting (decay detection).

## Features

- **File → Contributor Map** — per file: who committed, how often, last touch, ownership %.
- **Bus Factor** — how many people must disappear before knowledge is lost. BF=1 = high risk.
- **Decay Detection** — active files whose original owner has gone quiet (60+ days).
- **Knowledge Levels** — L1/L2/L3 per contributor per file.
- **Alerts** — email when bus factor drops to 1 on important files.

## Project structure

```
backend/    Python + FastAPI API + GitHub analysis pipeline (Render)
frontend/   React + Vite dashboard (Vercel)
docs/       Architecture + API reference
```

No AI/LLM in the MVP — bus factor, decay, and contributor mapping are pure
math over GitHub's commit API.

## Quick start

### Backend

```bash
cd backend
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env   # fill in secrets
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

Open http://localhost:5173. See `docs/api.md` for the API reference and
`docs/architecture.md` for the system design.

## License

See [LICENSE](LICENSE).


