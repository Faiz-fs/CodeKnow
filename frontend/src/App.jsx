import { Routes, Route, Link } from 'react-router-dom'
import Analyze from './pages/Analyze.jsx'

export default function App() {
  return (
    <div className="app">
      <header className="navbar">
        <Link to="/" className="brand">CodeKnow</Link>
        <nav>
          <Link to="/">Analyze</Link>
        </nav>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<Analyze />} />
        </Routes>
      </main>
    </div>
  )
}
