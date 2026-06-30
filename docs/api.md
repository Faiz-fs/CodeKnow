# CodeKnow — API Reference

Base URL (local): `http://localhost:8000`

## Health

### `GET /health`

Response:
```json
{ "status": "ok" }
```

## Auth (GitHub OAuth)

### `GET /auth/github`

Starts the OAuth flow. Returns the GitHub authorization URL.

Response:
```json
{ "authorization_url": "https://github.com/login/oauth/authorize?...", "state": "..." }
```

### `GET /auth/github/callback?code=...&state=...`

Handles the OAuth callback. Exchanges the code for a token and mints a JWT.

## Analysis

### `POST /analyze/repo`

Body:
```json
{ "repo_url": "owner/repo" }
```

`repo_url` accepts either the short `owner/repo` form or a full GitHub URL
(`https://github.com/owner/repo`).

Response:
```json
{
  "repo": "owner/repo",
  "analyzed_at": "2026-06-30T10:00:00+00:00",
  "files": [
    {
      "path": "src/payment/reconciliation.py",
      "contributors": [
        { "author": "ravi", "commits": 43, "last_commit": "2024-11-02", "ownership_pct": 84.0 }
      ],
      "total_commits": 51,
      "bus_factor": 1
    }
  ]
}
```

### Field notes

- `ownership_pct`: share of that file's commits attributed to the author.
- `bus_factor`: how many top contributors account for >50% of commits.
- `last_commit`: ISO date of the author's most recent commit to that file.
