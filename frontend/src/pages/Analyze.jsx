import { useState } from 'react'
import { analyzeRepo } from '../api.js'

export default function Analyze() {
  const [repoUrl, setRepoUrl] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)

  async function onSubmit(e) {
    e.preventDefault()
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const data = await analyzeRepo(repoUrl)
      setResult(data)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <section>
      <h1>Analyze a repository</h1>
      <p>Enter a GitHub repo (e.g. <code>facebook/react</code>) to map its contributors and bus factor.</p>

      <form onSubmit={onSubmit} className="analyze-form">
        <input
          type="text"
          placeholder="owner/repo"
          value={repoUrl}
          onChange={(e) => setRepoUrl(e.target.value)}
          required
        />
        <button type="submit" disabled={loading}>
          {loading ? 'Analyzing…' : 'Analyze'}
        </button>
      </form>

      {error && <p className="error">{error}</p>}

      {result && (
        <div className="results">
          <h2>{result.repo}</h2>
          <p>Analyzed at: {result.analyzed_at}</p>
          <table>
            <thead>
              <tr>
                <th>File</th>
                <th>Commits</th>
                <th>Bus Factor</th>
                <th>Top Owner</th>
              </tr>
            </thead>
            <tbody>
              {result.files.map((f) => (
                <tr key={f.path}>
                  <td>{f.path}</td>
                  <td>{f.total_commits}</td>
                  <td className={f.bus_factor === 1 ? 'risk' : ''}>{f.bus_factor}</td>
                  <td>{f.contributors[0]?.author ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
