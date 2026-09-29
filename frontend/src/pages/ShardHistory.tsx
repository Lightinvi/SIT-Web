/** Cursor-paginated ledger for the signed-in member, twenty entries per request. */
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeft, ChevronDown } from 'lucide-react'
import { shardRequest, signedAmount } from '../api/shards'
import type { ShardPage, ShardRecord } from '../api/shards'
import shardIcon from '../assets/star_shard.png'
import '../components/StarShard.css'

/** Show immutable income/debit records with explicit loading, empty, and retry states. */
export default function ShardHistory() {
  const [records, setRecords] = useState<ShardRecord[]>([])
  const [cursor, setCursor] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const controller = useRef<AbortController | null>(null)
  const busy = useRef(false)
  const heading = useRef<HTMLHeadingElement>(null)
  useEffect(() => {
    heading.current?.focus(); window.scrollTo(0, 0)
    const request = new AbortController()
    controller.current = request
    shardRequest<ShardPage>('/records', { signal: request.signal }).then(data => {
      if (!request.signal.aborted) { setRecords(data.records); setCursor(data.nextCursor) }
    }).catch(cause => { if (!request.signal.aborted) setError(cause instanceof Error ? cause.message : '無法載入紀錄。') })
      .finally(() => { if (!request.signal.aborted) setLoading(false) })
    return () => request.abort()
  }, [attempt])
  /** Append the next exclusive ID page without shifting entries when new credits arrive. */
  async function more() {
    if (cursor === null || busy.current) return
    busy.current = true; setLoading(true); setError('')
    try {
      const data = await shardRequest<ShardPage>(`/records?before=${cursor}`, { signal: controller.current!.signal })
      if (!controller.current?.signal.aborted) { setRecords(rows => [...rows, ...data.records]); setCursor(data.nextCursor) }
    } catch (cause) { if (!controller.current?.signal.aborted) setError(cause instanceof Error ? cause.message : '無法載入紀錄。') }
    finally { busy.current = false; if (!controller.current?.signal.aborted) setLoading(false) }
  }
  return <section className="shard-history" aria-labelledby="shard-history-title">
    <Link to="/" className="profile-back"><ArrowLeft size={16} />返回首頁</Link>
    <h1 id="shard-history-title" tabIndex={-1} ref={heading}><img src={shardIcon} alt="" />星之碎片紀錄</h1><p className="shard-muted">Star Shard</p>
    {error && <div role="alert" className="shard-error">{error} <button onClick={() => { if (records.length) void more(); else { setLoading(true); setError(''); setAttempt(value => value + 1) } }} disabled={loading}>重試</button><a href="/api/auth/discord/login">登入帳號</a></div>}
    {!loading && !error && !records.length && <p className="shard-empty">尚無星之碎片紀錄。</p>}
    <ol className="shard-records">{records.map(row => <li key={row.id}>
      <div className="shard-record-main"><strong>{row.description || row.transactionType}</strong><span className={row.amount > 0 ? 'shard-credit' : 'shard-debit'}>{signedAmount(row.amount)}</span></div>
      <div className="shard-record-meta"><time dateTime={new Date(row.createdAt * 1000).toISOString()}>{new Date(row.createdAt * 1000).toLocaleString('zh-TW', { hour12: false })}</time><span>餘額 {row.afterBlance.toLocaleString('zh-TW')}</span></div>
      <dl><div><dt>類型</dt><dd>{row.transactionType === 'transaction' ? '成員轉帳' : row.transactionType}</dd></div><div><dt>{row.transactionType === 'transaction' ? row.amount > 0 ? '轉讓者 ID' : '接收者 ID' : '來源'}</dt><dd>{row.transactionSource}</dd></div><div><dt>交易前餘額</dt><dd>{row.beforeBlance.toLocaleString('zh-TW')}</dd></div><div><dt>紀錄編號</dt><dd>{row.id}</dd></div></dl>
    </li>)}</ol>
    {loading && <p role="status">正在載入紀錄…</p>}
    {cursor !== null && <button className="shard-more" disabled={loading} onClick={more}><ChevronDown size={17} />載入更多</button>}
  </section>
}
