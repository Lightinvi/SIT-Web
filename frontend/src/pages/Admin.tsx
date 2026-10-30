/** Administration screen authorized by the backend's live Discord role check. */
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeft, ArrowRight, Database, ScrollText, ShieldCheck, RefreshCw } from 'lucide-react'
import './AdminViewer.css'
import AdminShardGrant from '../components/AdminShardGrant'

/** Synchronize guild caches and stored permissions without exposing member lists. */
export default function Admin() {
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setState('loading')
    fetch('/api/admin/status', { signal: controller.signal, cache: 'no-store' })
      .then(async response => {
        const data = await response.json()
        if (!response.ok) throw new Error(data.error || '無法載入管理工具。')
        setState('ready'); setMessage('')
      }).catch(error => {
        if (!controller.signal.aborted) { setMessage(error.message); setState('error') }
      })
    return () => controller.abort()
  }, [attempt])

  /** Obtain the current CSRF token and perform one explicit synchronization. */
  async function synchronize() {
    setBusy(true); setMessage('')
    try {
      const sessionResponse = await fetch('/api/auth/session', { cache: 'no-store' })
      if (!sessionResponse.ok) throw new Error('無法確認登入狀態。')
      const session = await sessionResponse.json()
      if (!session.authenticated) throw new Error('請重新登入帳號。')
      const response = await fetch('/api/admin/sync', {
        method: 'POST', headers: { 'X-CSRF-Token': session.csrf_token },
      })
      const result = await response.json()
      if (!response.ok) throw new Error(result.error || '同步失敗，請稍後再試。')
      setMessage(`同步完成：${result.updatedMembers} 位網站成員、${result.memberCount} 位 Discord 成員、${result.roleCount} 個身份組；撤銷 ${result.revokedSessions} 筆登入。更新時間：${new Date(result.updatedAt * 1000).toLocaleString()}`)
      window.dispatchEvent(new Event('account-updated'))
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '同步失敗，請稍後再試。')
    } finally { setBusy(false) }
  }

  async function updateWardogs() {
    setBusy(true); setMessage('正在檢查 WARDOGS 更新，首次下載圖片可能需要數分鐘…')
    try {
      const sessionResponse = await fetch('/api/auth/session', { cache: 'no-store' })
      const session = await sessionResponse.json()
      if (!sessionResponse.ok || !session.authenticated) throw new Error('請重新登入帳號。')
      const response = await fetch('/api/admin/wardogs/update', { method: 'POST', headers: { 'X-CSRF-Token': session.csrf_token } })
      let result = await response.json()
      if (!response.ok) throw new Error(result.error || 'WARDOGS 更新失敗。')
      for (let tries = 0; result.running && tries < 200; tries++) {
        await new Promise(resolve => window.setTimeout(resolve, 3000))
        const status = await fetch('/api/admin/wardogs/status', { cache: 'no-store' })
        result = await status.json()
        if (!status.ok) throw new Error(result.error || '無法讀取更新進度。')
      }
      if (result.error) throw new Error(result.error)
      setMessage(result.running ? 'WARDOGS 資料仍在背景更新，請稍後查看資料庫。' : `WARDOGS 資料檢查完成。檢查時間：${new Date(result.checkedAt * 1000).toLocaleString()}`)
    } catch (error) { setMessage(error instanceof Error ? error.message : '更新失敗。') }
    finally { setBusy(false) }
  }

  return <section className="admin-viewer admin-home" aria-labelledby="admin-title">
    <Link to="/" className="profile-back"><ArrowLeft size={16} aria-hidden="true" />返回首頁</Link>
    <div className="admin-heading"><h1 id="admin-title">管理工具</h1><ShieldCheck size={24} aria-hidden="true" /></div>
    {state === 'loading' && <p role="status">驗證權限中…</p>}
    {state === 'error' && <button className="account-button" onClick={() => setAttempt(value => value + 1)}>重新載入</button>}
    {state === 'ready' && <>
      <nav aria-label="管理功能" className="admin-tools">
        <Link to="/admin/database"><Database size={24} aria-hidden="true" /><span>資料庫</span><ArrowRight size={18} aria-hidden="true" /></Link>
        <Link to="/admin/log"><ScrollText size={24} aria-hidden="true" /><span>後端紀錄</span><ArrowRight size={18} aria-hidden="true" /></Link>
      </nav>
      <div className="admin-sync-row"><h2><ShieldCheck size={20} aria-hidden="true" />權限與 Discord 快取</h2>
      <button className="admin-sync-button" disabled={busy} onClick={synchronize}><RefreshCw size={17} aria-hidden="true" className={busy ? 'admin-spinning' : ''} />{busy ? '同步中…' : '同步權限與快取'}</button></div>
      <div className="admin-sync-row"><h2><Database size={20} aria-hidden="true" />WARDOGS 資料</h2>
        <button className="admin-sync-button" disabled={busy} onClick={updateWardogs}><RefreshCw size={17} aria-hidden="true" />更新 WARDOGS 資料</button></div>
      <AdminShardGrant />
    </>}
    {message && <p className="profile-notice" role="status">{message}</p>}
  </section>
}
