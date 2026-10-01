/** Administration screen authorized by the backend's live Discord role check. */
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeft, RefreshCw } from 'lucide-react'

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

  return <section className="profile-page" aria-labelledby="admin-title">
    <Link to="/" className="profile-back"><ArrowLeft size={16} aria-hidden="true" />返回首頁</Link>
    <h1 id="admin-title">管理工具</h1>
    {state === 'loading' && <p role="status">驗證權限中…</p>}
    {state === 'error' && <button className="account-button" onClick={() => setAttempt(value => value + 1)}>重新載入</button>}
    {state === 'ready' && <>
      <h2>權限與 Discord 快取</h2>
      <button className="account-button" disabled={busy} onClick={synchronize}><RefreshCw size={17} aria-hidden="true" />{busy ? '同步中…' : '同步權限與快取'}</button>
    </>}
    {message && <p className="profile-notice" role="status">{message}</p>}
  </section>
}
