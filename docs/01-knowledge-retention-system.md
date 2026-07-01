# Knowledge Retention System — Architecture & Development Plan

**Engine 1 of 3 — CodeKnow**
**Status: BUILDING NOW (P1)**
**Core question answered:** *"Who knows this code, and how concentrated is that knowledge?"*

---

## 1. Purpose

This engine reads Git commit history and converts it into two risk signals per file (and eventually per module): **Bus Factor** (how concentrated is ownership) and **Decay** (is the owner going quiet while others keep changing the file).

This engine is entirely **score-based, not AI-based**. Every number it produces is deterministic math over Git data — no LLM, no training data, no inference cost. This is intentional: the numbers must be explainable in one sentence ("bus factor is 1 because Ravi made 84% of commits and hasn't touched it in 107 days") for an engineering manager to trust them immediately.

---

## 2. System Architecture

```
┌─────────────────────────────────────────────────────┐
│                     CLIENT (React)                   │
└───────────────────────┬───────────────────────────────┘
                         │ JWT bearer
┌───────────────────────▼───────────────────────────────┐
│                 FastAPI Application                    │
│  ┌────────────┐  ┌────────────┐  ┌──────────────────┐ │
│  │ auth router │  │ github     │  │ analyze router    │ │
│  │ (OAuth+JWT) │  │ router     │  │ (/analyze/repo,   │ │
│  │             │  │ (/repos)   │  │  /at-risk)         │ │
│  └────────────┘  └────────────┘  └──────────────────┘ │
│         │               │                  │            │
│  ┌──────▼───────────────▼──────────────────▼─────────┐ │
│  │            services/github.py                       │ │
│  │  - fetch commits (paginated, concurrent)             │ │
│  │  - fetch per-commit file diffs                       │ │
│  │  - rate limit aware                                  │ │
│  └──────────────────────┬───────────────────────────┘ │
│                         │                                │
│  ┌──────────────────────▼───────────────────────────┐ │
│  │            services/analysis.py                     │ │
│  │  - build file → contributor map                     │ │
│  │  - calculate ownership %                             │ │
│  │  - calculate bus_factor                              │ │
│  │  - calculate decay status                             │ │
│  └──────────────────────┬───────────────────────────┘ │
└─────────────────────────┼───────────────────────────────┘
                          │
                ┌─────────▼──────────┐
                │  Postgres (local    │
                │  → Supabase later)  │
                │  users, repo_       │
                │  analyses (jsonb)   │
                └──────────────────────┘
```

---

## 3. Data Sources

- **GitHub commit history** (current) — via REST API, per-commit file-level diffs
- **GitLab commit history** (P2, deferred) — same shape, different API surface
- Slack / Jira / Confluence (mentioned in the original product vision as future contribution signals) are **explicitly out of scope** for now. Adding them means new OAuth flows, new rate limits, new data models — that's a different, much larger project. Revisit only after GitHub-only retention scoring is proven valuable to a real user.

---

## 4. Core Calculations

### 4.1 Contributor Map (done)

For each file touched in the analyzed commit range:
- List of contributors with: commit count, last commit date, ownership % (their commits / total commits to that file)

### 4.2 Bus Factor (done — verify formula matches this)

Minimum number of contributors needed to account for ≥50% of a file's total commits. A single dominant contributor (>50% alone) = bus factor 1 = maximum risk.

### 4.3 Decay Detection (in progress)

A file is "decaying" when its owner (highest ownership %) has gone quiet on it while others keep changing it — meaning knowledge is leaking out of the system in real time.

```
days_since_owner_touched = most_recent_commit_date - owner_last_commit_date
commits_since_owner_left = count of commits by others, after owner's last commit

Tiers:
  stable:    owner active within 60 days, OR 0 commits by others since
  decaying:  owner inactive 60+ days AND 1+ commits by others since
  critical:  owner inactive 90+ days AND 3+ commits by others since,
             OR >30% of file's commits happened after owner went quiet
```

Thresholds configurable: `DECAY_WARNING_DAYS`, `DECAY_CRITICAL_DAYS`, `DECAY_WARNING_COMMITS`, `DECAY_CRITICAL_COMMITS`, `DECAY_CRITICAL_CHANGE_PCT`.

### 4.4 Module-Level Aggregation (not started — next priority after decay)

Currently everything is **file-level**. The product story is stronger at the **module/folder level**: "your entire payment module has bus factor 1" lands harder than "this one file has bus factor 1." Aggregate file-level scores up by folder path once decay detection ships. This is a rollup of existing data, not a new data collection effort.

---

## 5. Storage Model

```sql
users (
  id, email, name, github_id,
  github_access_token_encrypted,
  created_at, updated_at
)

repo_analyses (
  id, user_id, repo_full_name, platform,
  analyzed_at, raw_result JSONB
)
```

`raw_result` holds the full per-file contributor/bus-factor/decay payload. No schema change needed when decay or module-rollup data is added — it's additive JSON.

---

## 6. API Surface

| Endpoint | Purpose |
|---|---|
| `GET /auth/github/login` | Start OAuth flow |
| `GET /auth/github/callback` | Complete OAuth, issue JWT |
| `GET /github/repos` | List user's repos |
| `POST /analyze/repo` | Run full analysis, persist, return result |
| `GET /analyze/repo/{repo}/at-risk` | Return only decaying/critical files, sorted by severity |

---

## 7. Build Order (this engine only)

1. ~~OAuth + JWT auth~~ — done
2. ~~Repo listing~~ — done
3. ~~Commit-level contributor mapping~~ — done
4. ~~Bus factor calculation~~ — done
5. Decay detection — in progress
6. Module/folder-level aggregation — next
7. Frontend dashboard to visualize bus factor + decay
8. Email alerts when bus factor drops to 1 (deferred to after frontend)
9. GitLab support (P2, deferred until GitHub version is validated with a real user)

---

## 8. What This Engine Deliberately Does NOT Do

- No AI/LLM calls — pure deterministic computation
- No Slack/Jira/Confluence integration (yet)
- No architecture/dependency graph (that's Engine 2)
- No cross-engine correlation (that's Engine 3 — cannot exist until Engine 2 also exists)

---

## 9. Maintenance Notes

- Commit fetching is capped (`MAX_COMMITS_TO_ANALYZE`, default 500) to control GitHub rate limit usage and response time on large repos. Revisit this cap only if real usage shows it's insufficient — don't pre-optimize for repos you haven't tested against yet.
- Re-running `/analyze/repo` on the same repo should upsert, not duplicate, stored analysis.
- As repo size/commit count grows, the main scaling risk is GitHub API rate limits and request latency — not the math itself, which stays cheap regardless of repo size.
