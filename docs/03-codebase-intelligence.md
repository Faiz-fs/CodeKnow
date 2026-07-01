# Codebase Intelligence — Architecture & Plan

**Engine 3 of 3 — CodeKnow**
**Status: BUILD LAST (P3 — requires both Engine 1 and Engine 2 fully working)**
**Core question answered:** *"Given everything we know about people AND code structure, what is the actual risk, and what should we do about it?"*

---

## 1. Purpose

This is the correlation layer — the part that makes CodeKnow more than just "a GitHub analytics tool." It joins the people-knowledge data (Engine 1) against the structural code graph (Engine 2) to produce compound risk signals and actionable outputs that neither engine could generate alone.

The canonical example:
> "Ravi's bus factor on `reconciliation.py` is 1, he hasn't touched it in 107 days, AND 6 other services depend on it via import chains."

The first two facts come from Engine 1. The third comes from Engine 2. The compound insight — this is CRITICAL, not just decaying — requires both.

---

## 2. Hard Dependency — Do Not Start This Until

- Engine 1 (Retention System) is fully working and has been validated by at least one real user beyond yourself
- Engine 2 (Knowledge Graph) has a working file-to-file import graph for at least one repo
- Both engines are persisting data to the same Postgres database this engine will query

There is no shortcut here. This is a data dependency, not a priority preference.

---

## 3. Is This AI-Based?

**Mostly not.** The core risk calculations are deterministic joins across Engine 1 and Engine 2 data. AI enters only at the presentation layer — turning structured risk data into readable prose, and optionally accepting natural language questions. The AI layer never touches the risk math itself.

```
Deterministic core (score-based):
  bus_factor (Engine 1) +
  decay status (Engine 1) +
  blast radius from dependency graph (Engine 2)
  → compound risk score per file/module

AI layer (optional, thin, cheap):
  structured risk data → LLM → plain English summary or answer
```

---

## 4. Core Computations

### 4.1 Blast Radius Score

When a file has bus_factor = 1, it matters *a lot more* if 12 other files import it than if 0 files import it. The blast radius is a graph traversal from Engine 2's edges table.

```python
# Pseudo-code
def blast_radius(file_path, repo_id):
    # Traverse dependency edges outward from this node
    # Count unique downstream dependents (files, routes, tables)
    # Weighted by depth: direct dependents count more than transitive ones
    return {
        "direct_dependents": [...],
        "transitive_dependents": [...],
        "total_blast_radius": int,
        "critical_paths_affected": [...]  # API routes or DB tables at risk
    }
```

### 4.2 Knowledge Freshness Score

How accurate is the owner's knowledge of the *current* state of the file they supposedly own?

```
pct_file_changed_since_owner_last_touch =
  lines changed after owner's last commit / total lines in file

freshness_score = 1 - pct_file_changed_since_owner_last_touch

freshness 0.9 = owner's knowledge is ~90% current
freshness 0.3 = 70% of the file has changed since they last touched it
               — their knowledge is largely stale even if they're still "the owner"
```

### 4.3 Compound Risk Score

Joining Engine 1 + Engine 2 signals into one number per file:

```
compound_risk = weighted combination of:
  - bus_factor (lower = worse)
  - decay_status (stable/decaying/critical)
  - freshness_score (lower = worse)
  - blast_radius (higher = worse)
  - days_since_owner_touched (higher = worse)

All inputs are deterministic numbers.
The weighting formula should be configurable (config.py) so it can be
tuned as you get real user feedback about what matters most.
```

### 4.4 Departure Impact Simulation

The "what if Ravi leaves?" query — the anchor demo moment for the product:

```
Given: engineer name
1. Find all files where engineer is bus_factor owner (Engine 1)
2. For each file: get freshness score, blast radius, decay status
3. Traverse dependency graph outward from those files (Engine 2)
4. Identify downstream API routes, DB tables, services at risk
5. Return: affected files, blast radius count, whether any other
   engineer has sufficient knowledge to cover each file
```

This is a database query pipeline, not an AI computation. The output is structured data. AI is optionally used at the end to explain it in plain English (see section 6).

---

## 5. New API Endpoints (Engine 3 adds these)

| Endpoint | Purpose |
|---|---|
| `GET /intelligence/repo/{repo}/compound-risk` | Full compound risk report joining Engine 1 + Engine 2 data |
| `GET /intelligence/repo/{repo}/departure-impact?engineer=ravi@co.com` | Simulate departure of one engineer |
| `GET /intelligence/repo/{repo}/risk-digest` | AI-generated plain-English summary of current risk state |
| `GET /intelligence/repo/{repo}/onboarding-path?engineer=anjali@co.com` | Ranked module learning path for a new hire (Phase 3+) |

The first two endpoints are pure deterministic computation.
The last two involve an LLM call (via OpenRouter) — see section 6.

---

## 6. Where AI Fits — Exactly

### Feature: Risk Digest (first AI feature to build, when you get here)

Takes the structured compound risk output and turns it into a human-readable summary for a busy engineering manager who doesn't want to read a table of 40 risky files.

**How it works:**

```
1. Run compound risk calculation (deterministic, fast)
2. Take the top N risky files as structured JSON
3. Send to OpenRouter (Deepseek V3 or Gemini Flash — cheap, fast, good enough)
4. Receive plain-English summary
5. Return summary alongside the raw data (never replace the raw data with the summary)

Estimated token cost per digest: ~800 input tokens + ~300 output tokens
At Deepseek V3 pricing: ~$0.0003 per digest
Safe to offer as a free feature — trivial cost
```

**What to send to the LLM (structured, not raw code):**

```json
{
  "repo": "payment-service",
  "analyzed_at": "2026-07-01",
  "critical_files_count": 6,
  "top_risks": [
    {
      "path": "reconciliation.py",
      "owner": "ravi@company.com",
      "bus_factor": 1,
      "days_since_owner_touched": 107,
      "freshness_score": 0.38,
      "blast_radius": 6,
      "decay_status": "critical"
    }
  ],
  "engineers_at_risk": [
    {"name": "Ravi", "files_solely_owned": 4, "total_blast_radius": 14}
  ]
}
```

**What NOT to send to the LLM:**
- Raw code
- Full commit history
- Binary or generated files

Sending raw code to an LLM makes this expensive per request and adds no analytical value — the risk calculations are already done. The LLM's only job here is to write prose, not to understand code.

### Feature: Natural Language Query ("What breaks if Ravi leaves?")

```
User query (plain English)
       │
       ▼
LLM (intent parsing) → structured query params
       │               { action: "departure_impact", engineer: "ravi@..." }
       ▼
Deterministic backend pipeline (departure impact simulation above)
       │
       ▼
Structured result JSON
       │
       ▼
LLM (explanation) → plain English answer with the structured data attached
```

The LLM is a translator at both ends. The actual computation is always deterministic. This is important for trust — when a CTO asks "what breaks if Ravi leaves?", they need to trust the answer. A fully LLM-derived answer is not trustworthy. A deterministic computation explained by an LLM is.

### Do NOT Use AI For

- Calculating bus factor (it's arithmetic)
- Deciding decay status (it's a threshold comparison)
- Building the import graph (it's static analysis)
- Storing or retrieving data
- Anything where the output must be auditable and explainable to a skeptical engineering manager

---

## 7. OpenRouter Configuration

```python
# config.py additions for Engine 3

OPENROUTER_API_KEY = env("OPENROUTER_API_KEY")

# Model choice — start cheap and fast, upgrade if quality is insufficient
DIGEST_MODEL = "deepseek/deepseek-chat"          # ~$0.0003/digest
QUERY_MODEL  = "deepseek/deepseek-chat"          # same
# Upgrade path if needed: "google/gemini-flash-1.5" or "anthropic/claude-haiku-4-5"

DIGEST_MAX_TOKENS = 500    # enough for a clear paragraph summary
QUERY_MAX_TOKENS  = 600    # slightly more for a structured answer
```

No fine-tuning, no model training, no custom inference infrastructure. Standard API calls to an existing model. This is the entire "AI layer" — everything else in the product is Python + Postgres.

---

## 8. Phase Breakdown

### Phase 1 (Engine 3 MVP — after Engine 1 + 2 exist)
- Compound risk score calculation
- Blast radius traversal
- `/compound-risk` endpoint
- `/departure-impact` endpoint

### Phase 2 (first AI features)
- Risk Digest (LLM prose summary) — easiest AI feature, highest demo value
- Natural language query interface

### Phase 3 (differentiated, post-revenue)
- Onboarding path generator (new hire → ranked learning modules)
- Knowledge transfer playbook (auto-generate transfer plan for departing engineer)
- Weekly email digest with AI summary
- CTO-level reporting dashboard (aggregate bus factor across all repos)

---

## 9. Maintenance Notes

- **Risk scores should be recalculated on demand**, not on a background schedule, until you have enough users to justify the compute and complexity of scheduled jobs
- **AI outputs must be cached** per (repo, analyzed_at) pair — never re-call the LLM for a digest you've already generated for the same analysis run. LLM calls are cheap but not free
- **Always return raw structured data alongside AI output** — never let the frontend show only the LLM's prose. The prose can be wrong; the data underneath it is deterministic. Give users both

---

## 10. What This Engine Deliberately Does NOT Do

- No model training or fine-tuning — ever (the value is in the data moat and the correlation logic, not in a proprietary model)
- No AI-driven risk calculations — all risk math is deterministic and explainable
- No Slack/HRIS/Jira integration in the first version of this engine
- No real-time streaming or event-driven updates until on-demand analysis is validated at scale
