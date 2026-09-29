/** Confirmed member-to-member Star Shard transfer with a stable retry identifier. */
import { useEffect, useRef, useState } from 'react'
import { Check, Send, X } from 'lucide-react'
import Select from 'react-select'
import { shardRequest } from '../api/shards'
import type { ShardMember } from '../api/shards'

/** Search registered members and require a separate confirmation before writing. */
export default function ShardTransfer({ csrf, balance, onClose }: { csrf: string; balance: number | null; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [query, setQuery] = useState('')
  const [members, setMembers] = useState<ShardMember[]>([])
  const [recipient, setRecipient] = useState<ShardMember | null>(null)
  const [amount, setAmount] = useState('')
  const [stage, setStage] = useState<'edit' | 'confirm' | 'done'>('edit')
  const [loading, setLoading] = useState(true)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState('')
  const [searchError, setSearchError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const requestId = useRef(crypto.randomUUID())
  const locked = useRef(false)
  const alive = useRef(true)
  const quantity = Number(amount)
  const valid = recipient && Number.isSafeInteger(quantity) && quantity > 0
  useEffect(() => {
    alive.current = true
    const element = dialog.current!
    const previous = document.activeElement as HTMLElement | null
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    element.showModal()
    return () => { alive.current = false; element.close(); document.body.style.overflow = overflow; previous?.focus() }
  }, [])
  useEffect(() => {
    const controller = new AbortController()
    const timeout = window.setTimeout(() => {
      setLoading(true); setSearchError('')
      shardRequest<{ members: ShardMember[] }>(`/members?q=${encodeURIComponent(query)}`, { signal: controller.signal })
        .then(data => { if (!controller.signal.aborted) setMembers(data.members) })
        .catch(() => { if (!controller.signal.aborted) setSearchError('無法載入成員，請重試。') })
        .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    }, 200)
    return () => { controller.abort(); window.clearTimeout(timeout) }
  }, [query, attempt])
  /** Retry an uncertain response with the same UUID instead of debiting twice. */
  async function send() {
    if (!valid || locked.current) return
    locked.current = true; setSending(true); setError('')
    try {
      await shardRequest('/transfer', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
        body: JSON.stringify({ recipientId: recipient.userId, amount: quantity, requestId: requestId.current }) })
      window.dispatchEvent(new Event('shards-changed'))
      if (alive.current) setStage('done')
    } catch (cause) { if (alive.current) setError(cause instanceof Error && cause.name === 'Error' ? cause.message : '連線中斷，請按確認重試以確認交易結果。') }
    finally { locked.current = false; if (alive.current) setSending(false) }
  }
  return <dialog className="shard-dialog" ref={dialog} aria-labelledby="shard-transfer-title" onCancel={event => { event.preventDefault(); if (!sending) onClose() }}>
    <header><h2 id="shard-transfer-title">{stage === 'done' ? '給予成功' : stage === 'confirm' ? '確認給予' : '給予星之碎片'}</h2><button className="shard-icon-button" title="關閉" aria-label="關閉給予視窗" disabled={sending} onClick={onClose}><X size={20} /></button></header>
    {stage === 'edit' ? <form onSubmit={event => { event.preventDefault(); if (valid) { setError(''); setStage('confirm') } }}>
      <p className="shard-muted">目前餘額：{balance === null ? '暫無資料' : balance.toLocaleString('zh-TW')}</p>
      <label htmlFor="shard-recipient">給予對象</label>
      <Select<ShardMember>
        inputId="shard-recipient" instanceId="shard-recipient" name="recipientId"
        className="shard-member-select" classNamePrefix="shard-select"
        value={recipient} inputValue={query} options={loading || searchError ? [] : members}
        getOptionValue={member => member.userId}
        getOptionLabel={member => `${member.displayName || member.username || member.userId} · ${member.username || member.userId}`}
        filterOption={null} isSearchable isClearable isLoading={loading}
        placeholder="搜尋名稱或 Discord ID"
        loadingMessage={() => '載入成員中…'}
        noOptionsMessage={() => searchError || '沒有符合的成員'}
        screenReaderStatus={({ count }) => `${count} 位成員可供選擇`}
        menuPlacement="auto" menuPosition="fixed" maxMenuHeight={180}
        onInputChange={(value, meta) => {
          if (meta.action === 'input-change') {
            setQuery(value.slice(0, 100)); setRecipient(null); setLoading(true); setSearchError('')
          } else if (query) { setQuery(''); setLoading(true) }
        }}
        onChange={member => setRecipient(member)}
        styles={{
          control: (base, state) => ({ ...base, minHeight: 44, borderRadius: 5, borderColor: state.isFocused ? '#176a61' : '#b8c5c9', boxShadow: state.isFocused ? '0 0 0 1px #176a61' : 'none' }),
          option: (base, state) => ({ ...base, overflowWrap: 'anywhere', backgroundColor: state.isSelected ? '#176a61' : state.isFocused ? '#edf5f3' : 'white', color: state.isSelected ? 'white' : '#263a42' }),
          menu: base => ({ ...base, zIndex: 2 }),
        }}
      />
      {searchError && <p role="alert">{searchError}<button type="button" onClick={() => { setLoading(true); setAttempt(value => value + 1) }}>重試</button></p>}
      <label htmlFor="shard-amount">數量</label><input id="shard-amount" type="number" inputMode="numeric" min="1" max={Number.MAX_SAFE_INTEGER} step="1" required value={amount} onChange={event => setAmount(event.target.value)} />
      <footer><button type="button" onClick={onClose}>取消</button><button className="shard-primary" disabled={!valid || loading || !!searchError}><Send size={16} />下一步</button></footer>
    </form> : <>
      <p className="shard-transfer-amount">{quantity.toLocaleString('zh-TW')} <span>星之碎片</span></p>
      <p className="shard-recipient-name">給予 {recipient?.displayName || recipient?.username}</p><p className="shard-muted">{recipient?.userId}</p>
      {stage === 'confirm' && <p>確認後將立即扣除餘額，轉帳無法撤回。</p>}
      {error && <p className="shard-error" role="alert">{error}</p>}
      <footer>{stage === 'done' ? <button className="shard-primary" onClick={onClose}><Check size={16} />完成</button> : <><button disabled={sending || !!error} onClick={() => setStage('edit')}>返回修改</button><button className="shard-primary" disabled={sending} onClick={send}><Send size={16} />{sending ? '處理中…' : '確認給予'}</button></>}</footer>
    </>}
  </dialog>
}
