/** WARDOGS feature category using the shared feature navigation layout. */
import { ArrowLeft, ArrowUpRight, Database } from 'lucide-react'
import { Link } from 'react-router-dom'
import './Home.css'

export default function Wardogs() {
  return <section className="home-functions" aria-labelledby="wardogs-title">
    <Link className="home-return" to="/"><ArrowLeft size={17} />返回功能導覽</Link>
    <h1 id="wardogs-title">WARDOGS</h1>
    <div className="home-function-grid">
      <Link className="home-feature" to="/wardogs/database">
        <Database size={64} aria-hidden="true" /><span>資料庫</span><ArrowUpRight className="home-feature-arrow" size={18} aria-hidden="true" />
      </Link>
    </div>
  </section>
}
