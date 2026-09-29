/** Header balance and private Star Shard actions for an authenticated account. */
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { History, Send, RefreshCw } from 'lucide-react'
import shardIcon from '../assets/star_shard.png'
import { shardRequest } from '../api/shards'
import ShardTransfer from './ShardTransfer'
import './StarShard.css'

/** Refresh the displayed balance on transfers, window focus, and periodic polling. */
export default function StarShard({ csrf }: { csrf: string }) {
  const [balance, setBalance] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [open, setOpen] = useState(false)
  const [giving, setGiving] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const root = useRef<HTMLDivElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    const controller = new AbortController()
    let pending = false
    /** Avoid overlapping balance refreshes and ignore responses after logout. */
    async function refresh() {
      if (pending) return
      pending = true
      try {
        const result = await shardRequest<{ balance: number }>('/balance', { signal: controller.signal })
        if (!controller.signal.aborted) { setBalance(result.balance); setError('') }
      } catch { if (!controller.signal.aborted) setError('餘額暫時無法更新') }
      finally { pending = false }
    }
    void refresh()
    window.addEventListener('focus', refresh)
    window.addEventListener('shards-changed', refresh)
    const interval = window.setInterval(refresh, 60000)
    return () => { controller.abort(); window.clearInterval(interval); window.removeEventListener('focus', refresh); window.removeEventListener('shards-changed', refresh) }
  }, [attempt])
  useEffect(() => {
    if (!open) return
    /** Close the action popover when clicking outside or pressing Escape. */
    const outside = (event: PointerEvent) => { if (!root.current?.contains(event.target as Node)) setOpen(false) }
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') { setOpen(false); trigger.current?.focus() } }
    document.addEventListener('pointerdown', outside)
    document.addEventListener('keydown', escape)
    return () => { document.removeEventListener('pointerdown', outside); document.removeEventListener('keydown', escape) }
  }, [open])
  return <>
    <div className="shard-wallet" ref={root} onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false) }}>
      <button className="shard-balance" ref={trigger} aria-label={`星之碎片餘額：${error || balance?.toLocaleString('zh-TW') || '0'}`} title="星之碎片 Star Shard" aria-expanded={open} aria-controls="shard-actions" onClick={() => setOpen(!open)}>
        <img src={shardIcon} alt="" /><span>{error ? '—' : balance === null ? '…' : balance.toLocaleString('zh-TW')}</span>
      </button>
      {open && <div className="shard-actions" id="shard-actions">
        {error && <><p role="status">{error}</p><button onClick={() => setAttempt(value => value + 1)}><RefreshCw size={16} />重試</button></>}
        <Link to="/star-shards" onClick={() => setOpen(false)}><History size={16} />紀錄</Link>
        <button onClick={() => { setOpen(false); setGiving(true) }}><Send size={16} />給予</button>
      </div>}
    </div>
    {giving && <ShardTransfer csrf={csrf} balance={balance} onClose={() => { setGiving(false); trigger.current?.focus() }} />}
  </>
}
