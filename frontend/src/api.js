// Thin API client for the CodeKnow backend.
// In dev, Vite proxies /analyze, /auth, /health to the backend (see vite.config.js).

const BASE = import.meta.env.VITE_API_BASE_URL || ''

export async function analyzeRepo(repoUrl) {
  const res = await fetch(`${BASE}/analyze/repo`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ repo_url: repoUrl }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `Analysis failed (${res.status})`)
  }
  return res.json()
}
