/** Accessible Discord invitation picker backed by database settings and click records. */
import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { ArrowUpRight, Check, LoaderCircle, ShieldCheck, UserRound, Users, X } from 'lucide-react'
import { getInvitations, requestInvitation } from '../api/invitations'
import type { Invitation } from '../api/invitations'
import './InvitationDialog.css'

/** Show role choices, require a referrer for regular membership, and record before leaving. */
export default function InvitationDialog({ onClose }: { onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [invitations, setInvitations] = useState<Invitation[]>([])
  const [csrf, setCsrf] = useState('')
  const [selected, setSelected] = useState('')
  const [code, setCode] = useState('')
  const [loading, setLoading] = useState(true)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const requestId = useRef('')
  const pending = useRef<AbortController | null>(null)
  const alive = useRef(false)
  const choice = invitations.find(item => item.role === selected)

  useEffect(() => {
    alive.current = true
    const element = dialog.current!
    const previous = document.activeElement as HTMLElement | null
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    element.showModal()
    return () => {
      alive.current = false
      pending.current?.abort()
      element.close()
      document.body.style.overflow = overflow
      previous?.focus()
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    let disposed = false
    const timeout = window.setTimeout(() => controller.abort(), 15000)
    getInvitations(controller.signal).then(data => {
      if (disposed) return
      setInvitations(data.invitations)
      setCsrf(data.csrf_token)
    }).catch((cause: unknown) => {
      if (!disposed) setError(cause instanceof Error && cause.name !== 'AbortError' ? cause.message : '載入逾時，請重試。')
    }).finally(() => { window.clearTimeout(timeout); if (!disposed) setLoading(false) })
    return () => { disposed = true; controller.abort(); window.clearTimeout(timeout) }
  }, [attempt])

  /** Reserve a tab during the click, then open the invite only after recording succeeds. */
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!choice || choice.isExpired || pending.current) return
    if (choice.requiresCode && !code.trim()) { setError('請輸入管理員派發的代碼。'); return }
    // Open synchronously so browser popup protection does not block the async result.
    const invitationTab = window.open('about:blank', '_blank')
    if (!invitationTab) { setError('無法開啟新分頁，請允許此網站開啟彈出式視窗後重試。'); return }
    invitationTab.opener = null
    let opened = false
    const controller = new AbortController()
    pending.current = controller
    setSending(true)
    setError('')
    const timeout = window.setTimeout(() => controller.abort(), 45000)
    try {
      requestId.current ||= crypto.randomUUID()
      const url = await requestInvitation(choice.role, code.trim(), requestId.current, csrf, controller.signal)
      if (alive.current) {
        if (invitationTab.closed) { setError('新分頁已關閉，請重試。'); return }
        invitationTab.location.replace(url)
        opened = true
        requestId.current = ''
      }
    } catch (cause) {
      if (alive.current) setError(cause instanceof Error && cause.name !== 'AbortError' ? cause.message : '連線逾時，請重試。')
    } finally {
      if (!opened) invitationTab.close()
      window.clearTimeout(timeout)
      pending.current = null
      if (alive.current) setSending(false)
    }
  }

  return <dialog ref={dialog} className="invitation-dialog" aria-labelledby="invitation-title"
    aria-describedby="invitation-contact" onCancel={event => { event.preventDefault(); onClose() }}>
    <div className="invitation-heading">
      <div><p>SIT COMMUNITY</p><h2 id="invitation-title">加入 Discord</h2></div>
      <button type="button" className="invitation-close" aria-label="關閉邀請視窗" title="關閉邀請視窗" onClick={onClose}><X size={21} /></button>
    </div>
    <form onSubmit={submit}>
      {loading ? <p className="invitation-loading" role="status"><LoaderCircle size={20} />正在載入加入選項…</p> : <>
        <fieldset className="invitation-options" disabled={sending}>
          <legend>選擇加入身分</legend>
          {invitations.map(item => {
            const Icon = item.requiresCode ? ShieldCheck : item.role === '訪客' ? UserRound : Users
            return <label key={item.role} className={'invitation-option' + (selected === item.role ? ' selected' : '') + (item.isExpired ? ' expired' : '')}>
              <input type="radio" name="invitation-role" value={item.role} checked={selected === item.role}
                disabled={item.isExpired} onChange={() => { setSelected(item.role); setCode(''); setError(''); requestId.current = '' }} />
              <Icon className="invitation-role-icon" size={23} aria-hidden="true" />
              <span className="invitation-option-text"><strong>{item.role}{item.isExpired && <small>暫停使用</small>}</strong><span>{item.description}</span></span>
              <span className="invitation-check" aria-hidden="true">{selected === item.role && <Check size={14} />}</span>
            </label>
          })}
        </fieldset>
        {!invitations.length && !error && <p className="invitation-empty">目前沒有可使用的邀請。</p>}
        {choice?.requiresCode && <div className="invitation-code">
          <label htmlFor="administrator-code">代碼</label>
          <input id="administrator-code" name="administrator-code" autoComplete="off" autoCapitalize="none" spellCheck={false}
            placeholder="請輸入管理員派發的代碼" maxLength={64} required disabled={sending}
            value={code} onChange={event => { setCode(event.target.value); setError(''); requestId.current = '' }} />
        </div>}
      </>}
      {error && <p className="invitation-error" role="alert">{error}</p>}
      {!loading && !invitations.length && error && <button type="button" className="invitation-retry" onClick={() => { setError(''); setLoading(true); setAttempt(value => value + 1) }}>重新載入</button>}
      <div className="invitation-footer">
        <p id="invitation-contact">若邀請連結失效，請聯繫 <span>discord/@lightinvi</span></p>
        <button className="invitation-submit" type="submit" disabled={loading || sending || !choice || choice.isExpired || (choice.requiresCode && !code.trim())}>
          {sending ? <><LoaderCircle size={17} />處理中…</> : <>前往 Discord<ArrowUpRight size={17} /></>}
        </button>
      </div>
    </form>
  </dialog>
}
