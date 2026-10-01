/** Confirmed system shard grants with searchable recipients and recoverable retries. */
import { useEffect, useRef, useState } from 'react'
import Select from 'react-select'
import { Check, Gift, RefreshCw, X } from 'lucide-react'
import type { ShardMember } from '../api/shards'

type Grant = { requestId: string; recipient: ShardMember; amount: number }

/** Preserve HTTP status so rejected input can be corrected without retrying forever. */
class RequestError extends Error {
  status: number
  constructor(message: string, status: number) { super(message); this.status = status }
}

/** Fetch protected admin JSON without exposing raw server errors. */
async function request(path: string, options: RequestInit = {}) {
  const response = await fetch(path, { cache: 'no-store', ...options,
    signal: options.signal ? AbortSignal.any([options.signal, AbortSignal.timeout(20000)]) : AbortSignal.timeout(20000) })
  const data = await response.json()
  if (!response.ok) throw new RequestError(data.error || '無法完成操作，請稍後再試。', response.status)
  return data
}

/** Only mounted after admin authorization; the API independently verifies every grant. */
export default function AdminShardGrant() {
  const [open, setOpen] = useState(false)
  const dialog = useRef<HTMLDialogElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const [recipient, setRecipient] = useState<ShardMember | null>(null)
  const [members, setMembers] = useState<ShardMember[]>([])
  const [query, setQuery] = useState('')
  const [amount, setAmount] = useState('')
  const [draft, setDraft] = useState<Grant | null>(null)
  const [pending, setPending] = useState(false)
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [session, setSession] = useState<{ id: string; csrf: string } | null>(null)
  const sending = useRef(false)
  useEffect(() => {
    if (!open) return
    const element = dialog.current!
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    element.showModal()
    return () => { element.close(); document.body.style.overflow = overflow; trigger.current?.focus() }
  }, [open])
  useEffect(() => {
    if (!open) return
    const controller = new AbortController()
    request('/api/auth/session', { signal: controller.signal }).then(data => {
      if (!data.authenticated || !data.user?.id) throw new Error('請重新登入帳號。')
      if (controller.signal.aborted) return
      setSession({ id: data.user.id, csrf: data.csrf_token })
      try {
        const saved = sessionStorage.getItem(`admin-grant:${data.user.id}`)
        if (saved) { setDraft(JSON.parse(saved)); setPending(true) }
      } catch { /* Browser storage is optional. */ }
    }).catch(cause => { if (!controller.signal.aborted) setError(cause.message) })
    return () => controller.abort()
  }, [open])
  useEffect(() => {
    if (!open) return
    const controller = new AbortController()
    setLoading(true)
    const timer = window.setTimeout(() => {
      request(`/api/admin/shards/members?q=${encodeURIComponent(query)}`, { signal: controller.signal })
        .then(data => { if (!controller.signal.aborted) setMembers(data.members) })
        .catch(cause => { if (!controller.signal.aborted) { setMembers([]); setError(cause.message) } })
        .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    }, 300)
    return () => { controller.abort(); clearTimeout(timer) }
  }, [query, open])

  /** Keep the same UUID until success so lost responses never create duplicate credits. */
  async function confirm() {
    if (!draft || !session || sending.current) return
    sending.current = true; setBusy(true); setPending(true); setError(''); setMessage('')
    const key = `admin-grant:${session.id}`
    try { sessionStorage.setItem(key, JSON.stringify(draft)) } catch { /* In-page retry remains protected. */ }
    try {
      await request('/api/admin/shards/grant', { method: 'POST', headers: {
        'Content-Type': 'application/json', 'X-CSRF-Token': session.csrf },
        body: JSON.stringify({ requestId: draft.requestId, recipientId: draft.recipient.userId, amount: draft.amount }) })
      try { sessionStorage.removeItem(key) } catch { /* Optional browser storage. */ }
      setMessage(`已發放 ${draft.amount.toLocaleString()} 點星之碎片給 ${draft.recipient.displayName || draft.recipient.username || draft.recipient.userId}。`)
      setDraft(null); setPending(false); setAmount(''); setRecipient(null)
      setOpen(false)
      window.dispatchEvent(new Event('shards-changed'))
    } catch (cause) {
      if (cause instanceof RequestError && cause.status === 400) {
        try { sessionStorage.removeItem(key) } catch { /* Optional browser storage. */ }
        setPending(false)
      }
      setError(cause instanceof Error ? cause.message : '請重試以確認發放結果。')
    }
    finally { sending.current = false; setBusy(false) }
  }

  const valid = recipient && Number.isSafeInteger(Number(amount)) && Number(amount) > 0
  return <>
    <div className="admin-sync-row"><h2><Gift size={20} aria-hidden="true" />發放星之碎片</h2>
      <button ref={trigger} className="admin-sync-button" aria-haspopup="dialog" onClick={() => setOpen(true)}><Gift size={17} aria-hidden="true" />發放星之碎片</button>
    </div>
    {message && <p role="status">{message}</p>}
    {open && <dialog ref={dialog} className="admin-grant admin-grant-dialog" aria-labelledby="grant-title" onCancel={event => { event.preventDefault(); if (!sending.current) setOpen(false) }}>
    <div className="admin-grant-heading"><h2 id="grant-title"><Gift size={20} aria-hidden="true" />發放星之碎片</h2><button className="account-button" disabled={busy} aria-label="關閉發放視窗" title="關閉發放視窗" onClick={() => setOpen(false)}><X size={20} /></button></div>
    {!draft ? <form onSubmit={event => { event.preventDefault(); if (valid && recipient) { setDraft({ requestId: crypto.randomUUID(), recipient, amount: Number(amount) }); setError(''); setMessage('') } }}>
      <label htmlFor="grant-recipient">發放對象</label>
      <Select<ShardMember> inputId="grant-recipient" aria-label="發放對象" options={members} value={recipient} onChange={setRecipient} onInputChange={(value, meta) => { if (meta.action === 'input-change') setQuery(value) }} getOptionValue={item => item.userId} getOptionLabel={item => `${item.displayName || item.username || '成員'} (${item.userId})`} filterOption={null} isSearchable isClearable isLoading={loading} placeholder="搜尋名稱或 Discord ID" noOptionsMessage={() => '找不到成員'} loadingMessage={() => '搜尋中…'} styles={{ container: base => ({ ...base, minWidth: 0, width: '100%' }), control: base => ({ ...base, minHeight: 44 }), valueContainer: base => ({ ...base, minWidth: 0 }), option: base => ({ ...base, overflowWrap: 'anywhere' }), menu: base => ({ ...base, zIndex: 20 }) }} />
      <label htmlFor="grant-amount">數量</label><input id="grant-amount" type="number" inputMode="numeric" min={1} max={Number.MAX_SAFE_INTEGER} step={1} value={amount} onChange={event => setAmount(event.target.value)} required />
      <button className="admin-sync-button" type="submit" disabled={!valid || !session}><Gift size={17} />確認發放內容</button>
    </form> : <div className="admin-grant-confirm">
      <p>發放對象：<strong>{draft.recipient.displayName || draft.recipient.username}</strong></p><p>Discord ID：{draft.recipient.userId}</p><p>系統發放：<strong>{draft.amount.toLocaleString()} 星之碎片</strong></p>
      <div><button className="admin-sync-button" onClick={confirm} disabled={busy || !session}>{pending ? <RefreshCw size={17} /> : <Check size={17} />}{busy ? '發放中…' : pending ? '重試確認結果' : '確認發放'}</button>
      {!pending && <button className="account-button" onClick={() => setDraft(null)}><X size={17} />返回修改</button>}</div>
    </div>}
    {error && <p role="alert">{error}</p>}
    </dialog>}
  </>
}
