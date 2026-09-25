import { useEffect, useRef, useState } from 'react'
import { ChevronDown, LogIn, LogOut, UserRound } from 'lucide-react'

import { Link, useNavigate } from 'react-router-dom'

import Avatar from './Avatar'

type LoginSession = { authenticated: boolean; user?: { name: string; avatar_url?: string | null }; csrf_token?: string }
const errors: Record<string, string> = {
  not_configured: 'Discord 登入尚未設定完成，請稍後再試。',
  not_member: '僅限 SIT Discord 群組成員登入，請先加入社群。',
  pending_member: '請先在 Discord 完成群組的成員審核。',
  invalid_state: '登入請求已失效，請重新登入。',
  cancelled: '已取消 Discord 登入。',
  discord_unavailable: 'Discord 驗證暫時無法完成，請稍後再試。',
}

export default function Account() {
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const dropdown = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const [account, setAccount] = useState<LoginSession>({ authenticated: false })
  const [loading, setLoading] = useState(true)
  const [message, setMessage] = useState(() => {
    const error = new URLSearchParams(window.location.search).get('auth_error')
    return error ? errors[error] || '登入失敗，請重新嘗試。' : ''
  })

  useEffect(() => {
    const url = new URL(window.location.href)
    const error = url.searchParams.get('auth_error')
    if (error) {
      url.searchParams.delete('auth_error')
      window.history.replaceState(null, '', url.pathname + url.search + url.hash)
    }
    const controller = new AbortController()
    const timeout = window.setTimeout(() => controller.abort(), 10000)
    let disposed = false
    fetch('/api/auth/session', { signal: controller.signal, cache: 'no-store' })
      .then(response => { if (!response.ok) throw new Error(); return response.json() })
      .then(data => { if (!disposed) setAccount(data) })
      .catch(() => { if (!disposed) setMessage('無法確認登入狀態，請稍後再試。') })
      .finally(() => { window.clearTimeout(timeout); if (!disposed) setLoading(false) })
    return () => { disposed = true; controller.abort(); window.clearTimeout(timeout) }
  }, [])

  useEffect(() => {
    if (!open) return
    const closeOutside = (event: PointerEvent) => {
      if (!dropdown.current?.contains(event.target as Node)) setOpen(false)
    }
    const closeEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { setOpen(false); trigger.current?.focus() }
    }
    document.addEventListener('pointerdown', closeOutside)
    document.addEventListener('keydown', closeEscape)
    return () => {
      document.removeEventListener('pointerdown', closeOutside)
      document.removeEventListener('keydown', closeEscape)
    }
  }, [open])

  async function logout() {
    setOpen(false)
    setLoading(true)
    try {
      const response = await fetch('/api/auth/logout', { method: 'POST', headers: { 'X-CSRF-Token': account.csrf_token || '' } })
      if (!response.ok) throw new Error()
      setAccount({ authenticated: false })
      navigate('/', { replace: true })
      setMessage('')
    } catch { setMessage('登出失敗，請稍後再試。') }
    finally { setLoading(false) }
  }

  return <div className="account-area">
    {loading ? <span className="account-loading" role="status">處理中…</span> : account.authenticated ?
      <div className="account-dropdown" ref={dropdown} onBlur={event => {
        if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false)
      }}>
        <button className="account-button account-trigger" ref={trigger} aria-expanded={open} aria-controls="account-actions" onClick={() => setOpen(value => !value)}>
          <Avatar src={account.user?.avatar_url} name={account.user?.name || '使用者'} className="header-avatar" /><span className="account-name">{account.user?.name}</span><ChevronDown size={16} aria-hidden="true" />
        </button>
        {open && <div className="account-actions" id="account-actions">
          <Link to="/profile" onClick={() => setOpen(false)}><UserRound size={17} aria-hidden="true" />個人資料</Link>
          <button onClick={logout}><LogOut size={17} aria-hidden="true" />登出</button>
        </div>}
      </div> :
      <a className="account-button" href="/api/auth/discord/login"><LogIn size={16} aria-hidden="true" />登入帳號</a>}
    {message && <div className="account-message" role="alert"><span>{message}</span><button aria-label="關閉登入提示" onClick={() => setMessage('')}>×</button></div>}
  </div>
}
