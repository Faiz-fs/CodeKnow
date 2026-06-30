# CodeKnow — API Reference

Base URL (local): `http://localhost:8080`

All endpoints are mounted under the `/codeknow` prefix.

## Health

### `GET /health`

Response:
```json
{ "status": "ok" }
```

## Auth (GitHub OAuth)

The login flow issues CodeKnow's own JWT (HS256, 7-day expiry). Send it as a
Bearer token on protected routes.

### `GET /codeknow/auth/github/login`

Redirects (307) to GitHub's OAuth consent screen with a signed `state` for CSRF
protection. Scopes requested: `repo`.

### `GET /codeknow/auth/github/callback?code=...&state=...`

Handles the OAuth callback. Verifies the signed state, exchanges the code for a
GitHub access token, fetches the GitHub user profile, upserts a `users` row
(storing the token encrypted), and mints a JWT.

Delivery is controlled by the `FRONTEND_REDIRECT` env var:

- **If set** — redirects (307) to that URL with `?token=<jwt>` appended.
- **If unset** — returns JSON:

```json
{
  "access_token": "<jwt>",
  "token_type": "bearer",
  "user": { "id": "...", "name": "...", "email": "...", "github_id": 123 }
}
```

> **Local dev note:** register `http://localhost:8080/codeknow/auth/github/callback` as
> the Authorization callback URL in your GitHub OAuth App settings.

## Analysis

### `POST /codeknow/analyze/repo`

**Protected** — requires `Authorization: Bearer <jwt>`.

Body:
```json
{ "repo_url": "https://github.com/owner/repo" }
```

`repo_url` accepts either the short `owner/repo` form or a full `github.com`
URL. Only `github.com` is supported today (GitLab is planned).

The endpoint fetches the most recent commits (default 500, configurable via
`MAX_COMMITS_TO_ANALYZE`), then concurrently fetches each commit's detail to get
its `files` array. Per-file contributor stats are aggregated from real file
attribution. The result is persisted to `repo_analyses`.

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
- `bus_factor`: how many top contributors account for >50% of commits to that file.
- `last_commit`: ISO date of the author's most recent commit to that file.

### Error responses

| Status | Meaning |
|---|---|
| 400 | Invalid `repo_url` (not github.com, or malformed) |
| 401 | Missing/invalid/expired JWT |
| 404 | Repository not found |
| 403 | GitHub token lacks scope or is rate-limited |
| 502 | GitHub API unreachable or token exchange failed |
