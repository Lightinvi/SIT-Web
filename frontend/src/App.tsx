import { useEffect, useState } from 'react'
import { ArrowUpRight, CircleCheck, RefreshCw, Users, WifiOff } from 'lucide-react'
import { getUsers } from './api/users'
import type { User } from './types/user'
import './App.css'

function App() {
  const [users, setUsers] = useState<User[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null)
  const [refresh, setRefresh] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    const timeout = window.setTimeout(() => controller.abort(), 10000)
    let disposed = false
    getUsers(controller.signal)
      .then((data) => {
        if (disposed) return
        setUsers(data.users)
        setUpdatedAt(new Date())
      })
      .catch((cause: unknown) => {
        if (disposed) return
        setError(controller.signal.aborted ? '連線逾時，請確認後端服務已啟動。'
          : cause instanceof Error ? cause.message : '連線失敗，請稍後重試。')
      })
      .finally(() => {
        window.clearTimeout(timeout)
        if (!disposed) setLoading(false)
      })
    return () => {
      disposed = true
      controller.abort()
      window.clearTimeout(timeout)
    }
  }, [refresh])

  function reload() {
    setLoading(true)
    setError('')
    setRefresh((value) => value + 1)
  }

  return (
    <>
      <header className="topbar">
        <a href="/" className="brand"><span className="brand-mark">S</span>SIT Web</a>
        <span className="workspace">工作空間 / 總覽</span>
        <span className="environment">開發環境</span>
      </header>
      <main>
        <div className="page-heading">
          <div><p className="eyebrow">WORKSPACE OVERVIEW</p><h1>工作空間總覽</h1><p className="muted">成員與最新連線狀態。</p></div>
          <button onClick={reload} disabled={loading}><RefreshCw size={16} className={loading ? 'spin' : ''} />{loading ? '更新中' : '重新整理'}</button>
        </div>
        <section className="summary" aria-label="工作空間摘要">
          <div><span className="metric-label"><Users size={17} />成員總數</span><strong data-testid="total">{updatedAt ? users.length : '—'}</strong><span className="muted">示範工作空間</span></div>
          <div><span className="metric-label">使用中</span><strong data-testid="active">{updatedAt ? users.filter(user => user.status === 'active').length : '—'}</strong><span className="muted">已啟用的成員</span></div>
          <div><span className="metric-label">連線狀態</span><strong className={'connection ' + (error ? 'failed' : '')}>{loading ? '連線中' : error ? '連線失敗' : '已連線'}</strong><span className="muted">{updatedAt ? '最後更新 ' + updatedAt.toLocaleTimeString('zh-TW', { hour12: false }) : '尚未同步'}</span></div>
        </section>
        <section aria-labelledby="members-heading">
          <div className="section-heading"><h2 id="members-heading">工作空間成員 <span className="tag">示範資料</span></h2><a href="/api/users" target="_blank" rel="noreferrer">查看原始資料<ArrowUpRight size={15} /></a></div>
          {error && <div className="error" role="alert"><WifiOff size={18} /><span>{error}{updatedAt && ' 下方保留上次取得的資料。'}</span></div>}
          <div className="table-scroll" aria-busy={loading}>
            <table>
              <thead><tr><th>成員</th><th>電子郵件</th><th>角色</th><th>狀態</th></tr></thead>
              <tbody>
                {users.map(user => <tr key={user.id} data-testid="user-row">
                  <td><span className="member"><span className="avatar" aria-hidden="true">{user.name.slice(0, 1)}</span><span data-field="name">{user.name}</span></span></td>
                  <td data-field="email">{user.email}</td><td data-field="role">{user.role}</td>
                  <td><span className={'status ' + user.status} data-field="status">{user.status === 'active' ? '使用中' : '待加入'}</span></td>
                </tr>)}
                {!users.length && <tr><td colSpan={4} className="empty">{loading ? '正在載入成員…' : error ? '暫時無法載入成員' : '尚無成員'}</td></tr>}
              </tbody>
            </table>
          </div>
          <p className="sync-note" role="status">{!loading && !error && <><CircleCheck size={15} />成員資料已同步</>}</p>
        </section>
        <footer><span>SIT Web</span><span>工作空間總覽</span></footer>
      </main>
    </>
  )
}
export default App
