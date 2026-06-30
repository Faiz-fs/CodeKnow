# CodeKnow — Frontend

React + Vite dashboard for visualizing repository contributor maps and bus factor.

## Layout

```
src/
  main.jsx          # React entrypoint + router
  App.jsx           # Layout + routes
  index.css         # Global styles
  api.js            # Backend API client
  pages/
    Analyze.jsx     # Repo input + results table
```

## Run locally

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

Open http://localhost:5173. API calls to `/analyze`, `/auth`, `/health` are
proxied to the FastAPI backend on port 8000 (see `vite.config.js`).
