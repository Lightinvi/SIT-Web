/** Pooled predictions with server-owned permissions, stakes and settlement. */
import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import Select from 'react-select'
import { ArrowLeft, ArrowRight, Check, Clock, Edit3, Plus, RefreshCw, Search, ShieldCheck, Trash2, Trophy, X } from 'lucide-react'
import shardIcon from '../assets/star_shard.png'
import './Predictions.css'

type Option = { id: string; label: string; total: number; ownAmount: number; odds: number | null }
type Market = { id: string; name: string; description: string; closesAt: number; settlesAt: number; baseReward: number; status: string; phase: string; version: number; options: Option[]; totalStaked: number; pool: number; ownAmount: number; ownPayout: number; winnerId: string | null; settlementMode: string | null }
type Session = { userId: string; csrfToken: string; balance: number }
type Intent = { path: string; body: Record<string, unknown>; summary: string }
type Pending = Intent & { requestId: string }
type Mode = 'create' | 'edit' | 'bet' | 'settle' | 'cancel'
const phaseLabels: Record<string, string> = { open: '開放押注', closed: '已截止', awaiting_result: '等待公布結果', settled: '已結算', cancelled: '已取消' }
const formatTime = (seconds: number) => new Date(seconds * 1000).toLocaleString(undefined, { hour12: false })
const odds = (value: number | null) => value === null ? '尚無下注' : `${value.toFixed(2)}x`
const statusOptions = [
  { value: 'all', label: '全部' }, { value: 'open', label: '開放押注' },
  { value: 'closed', label: '已截止／待結算' }, { value: 'finished', label: '已完成' },
]

/** Use calendar days in the browser timezone, including across daylight-saving changes. */
function defaultDateRange() {
  const start = new Date()
  const end = new Date(start)
  start.setDate(start.getDate() - 15)
  end.setDate(end.getDate() + 15)
  return { start: localInput(start.getTime() / 1000).slice(0, 10), end: localInput(end.getTime() / 1000).slice(0, 10) }
}

/** Convert inclusive local dates into a half-open timestamp interval for the API. */
function dateBounds(range: { start: string; end: string }) {
  const start = new Date(`${range.start}T00:00:00`)
  const end = new Date(`${range.end}T00:00:00`)
  end.setDate(end.getDate() + 1)
  return { closesFrom: String(start.getTime() / 1000), closesBefore: String(end.getTime() / 1000) }
}

/** Retain status codes so confirmed validation failures can be edited safely. */
class ApiError extends Error {
  status: number
  constructor(message: string, status: number) { super(message); this.status = status }
}

/** Fetch bounded private JSON, leaving uncertain writes retryable with their UUID. */
async function api(path: string, options: RequestInit = {}) {
  const response = await fetch(`/api/predictions${path}`, { ...options, cache: 'no-store',
    signal: options.signal ? AbortSignal.any([options.signal, AbortSignal.timeout(20000)]) : AbortSignal.timeout(20000) })
  const data = await response.json()
  if (!response.ok) throw new ApiError(data.error || '無法完成操作。', response.status)
  return data
}

/** Produce datetime-local input values without changing the user's timezone. */
function localInput(seconds: number) {
  const date = new Date(seconds * 1000)
  const pad = (value: number) => String(value).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`
}

/** Native modal traps focus and restores the initiating control when dismissed. */
function MarketDialog({ mode, market, sponsor, balance, locked, onClose, onSubmit }: {
  mode: Mode; market?: Market; sponsor: boolean; balance: number; locked: boolean;
  onClose: () => void; onSubmit: (intent: Intent) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const [name, setName] = useState(market?.name || '')
  const [description, setDescription] = useState(market?.description || '')
  const [labels, setLabels] = useState(['', ''])
  const [closes, setCloses] = useState(localInput(market?.closesAt || Date.now() / 1000 + 86400))
  const [settles, setSettles] = useState(localInput(market?.settlesAt || Date.now() / 1000 + 172800))
  const [bonus, setBonus] = useState('0')
  const [amount, setAmount] = useState('')
  const [option, setOption] = useState('')
  const [confirmation, setConfirmation] = useState<Intent | null>(null)
  const [error, setError] = useState('')
  const titles = { create: '建立預測盤', edit: '編輯預測盤', bet: '押注預測', settle: '公布結果並結算', cancel: '取消預測盤' }
  useEffect(() => {
    const element = dialog.current!
    const previous = document.activeElement as HTMLElement | null
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    element.showModal()
    return () => { element.close(); document.body.style.overflow = overflow; previous?.focus() }
  }, [])

  /** Build a preview only; the parent sends a command after explicit confirmation. */
  function preview() {
    setError('')
    let body: Record<string, unknown> = {}
    let summary = ''
    if (mode === 'create' || mode === 'edit') {
      const closeTime = market && closes === localInput(market.closesAt) ? market.closesAt : new Date(closes).getTime() / 1000
      const settleTime = market && settles === localInput(market.settlesAt) ? market.settlesAt : new Date(settles).getTime() / 1000
      const extra = Number(bonus)
      if (!Number.isSafeInteger(extra) || extra < 0 || !Number.isSafeInteger(extra + (market?.baseReward || 0))) { setError('基礎獎勵須為有效的非負整數。'); return }
      body = { name, description, closesAt: closeTime, settlesAt: settleTime }
      if (mode === 'create') body.options = labels
      else body.version = market!.version
      if (sponsor) body.baseReward = extra + (market?.baseReward || 0)
      summary = `${titles[mode]}「${name}」\n最後押注：${formatTime(closeTime)}\n結算時間：${formatTime(settleTime)}${sponsor ? `\n添加基礎獎勵：${extra} 點` : ''}`
    } else if (mode === 'bet') {
      const stake = Number(amount)
      if (!option || !Number.isSafeInteger(stake) || stake <= 0 || stake > balance) { setError('請選擇選項並輸入不超過餘額的正整數。'); return }
      body = { optionId: option, amount: stake }
      summary = `「${market!.name}」\n選項：${market!.options.find(item => item.id === option)?.label}\n押注 ${stake.toLocaleString()} 點星之碎片。\n押注後不可撤回，賠率以結算池額為準。`
    } else {
      if (mode === 'settle' && !option) { setError('請選擇獲勝選項。'); return }
      body = { version: market!.version, ...(mode === 'settle' ? { winnerId: option } : {}) }
      summary = mode === 'settle' ? `「${market!.name}」\n獲勝選項：${market!.options.find(item => item.id === option)?.label}\n確認後立即分配，無人押中則全部退款。結果不可修改。` : `取消「${market!.name}」並退還所有下注；基礎獎勵不派發。此操作不可復原。`
    }
    setConfirmation({ path: mode === 'create' ? '' : `/${market!.id}/${mode}`, body, summary })
  }

  return <dialog ref={dialog} className="prediction-dialog" aria-labelledby="prediction-dialog-title" onCancel={event => { event.preventDefault(); if (!locked) onClose() }}>
    <header><h2 id="prediction-dialog-title">{titles[mode]}</h2><button className="prediction-icon" disabled={locked} aria-label="關閉視窗" title="關閉視窗" onClick={onClose}><X size={20} /></button></header>
    {confirmation ? <><p className="prediction-confirm">{confirmation.summary}</p><div className="prediction-actions"><button className="prediction-primary" disabled={locked} onClick={() => onSubmit(confirmation)}><Check size={17} />確認送出</button><button disabled={locked} onClick={() => setConfirmation(null)}>返回修改</button></div></> : <form onSubmit={event => { event.preventDefault(); preview() }}>
      {(mode === 'create' || mode === 'edit') && <>
        <label>名稱<input required maxLength={120} value={name} onChange={event => setName(event.target.value)} /></label>
        <label>事件說明與判定依據<textarea maxLength={2000} rows={3} value={description} onChange={event => setDescription(event.target.value)} /></label>
        {mode === 'create' ? <fieldset><legend>押注選項</legend>{labels.map((label, index) => <div className="prediction-option-input" key={index}><input required maxLength={100} aria-label={`選項 ${index + 1}`} value={label} onChange={event => setLabels(items => items.map((value, position) => position === index ? event.target.value : value))} /><button type="button" className="prediction-icon" title="移除選項" aria-label={`移除選項 ${index + 1}`} disabled={labels.length <= 2} onClick={() => setLabels(items => items.filter((_, position) => position !== index))}><Trash2 size={16} /></button></div>)}<button type="button" disabled={labels.length >= 10} onClick={() => setLabels(items => [...items, ''])}><Plus size={16} />新增選項</button></fieldset> : <div className="prediction-fixed-options">{market!.options.map(item => <span key={item.id}>{item.label}</span>)}</div>}
        <label>最後押注時間<input type="datetime-local" required value={closes} disabled={mode === 'edit' && market!.closesAt <= Date.now() / 1000} onChange={event => setCloses(event.target.value)} /></label>
        <label>結算時間<input type="datetime-local" required value={settles} onChange={event => setSettles(event.target.value)} /></label>
        <p className="prediction-muted">時區：{Intl.DateTimeFormat().resolvedOptions().timeZone}</p>
        {sponsor && <label>添加基礎獎勵{market ? `（目前 ${market.baseReward.toLocaleString()} 點）` : ''}<input type="number" min={0} step={1} max={Number.MAX_SAFE_INTEGER} required value={bonus} onChange={event => setBonus(event.target.value)} /></label>}
      </>}
      {(mode === 'bet' || mode === 'settle') && <fieldset><legend>{mode === 'settle' ? '獲勝選項' : '押注選項'}</legend>{market!.options.map(item => <label className="prediction-choice" key={item.id}><input type="radio" name="option" required value={item.id} checked={option === item.id} onChange={() => setOption(item.id)} /><span>{item.label}</span>{mode === 'bet' && <strong>{odds(item.odds)}</strong>}</label>)}</fieldset>}
      {mode === 'bet' && <label>押注數量 · 餘額 {balance.toLocaleString()}<input required type="number" min={1} step={1} max={balance} value={amount} onChange={event => setAmount(event.target.value)} /></label>}
      {mode === 'cancel' && <p>將退還所有下注，且不派發基礎獎勵。</p>}
      {error && <p role="alert">{error}</p>}<button className="prediction-primary" type="submit" disabled={locked}>下一步<ArrowRight size={16} /></button>
    </form>}
  </dialog>
}

/** Browse active and historic markets, with member betting and live manager tools. */
export default function Predictions() {
  const { marketId } = useParams()
  const navigate = useNavigate()
  const [markets, setMarkets] = useState<Market[]>([])
  const [session, setSession] = useState<Session | null>(null)
  const [permissions, setPermissions] = useState({ canManage: false, canSponsor: false })
  const [permissionError, setPermissionError] = useState('')
  const [loading, setLoading] = useState(true)
  const [anonymous, setAnonymous] = useState(false)
  const [error, setError] = useState('')
  const [, setMessage] = useState('')
  const [status, setStatus] = useState('all')
  const [search, setSearch] = useState('')
  const [query, setQuery] = useState('')
  const [dates, setDates] = useState(defaultDateRange)
  const [appliedDates, setAppliedDates] = useState(dates)
  const [dateError, setDateError] = useState('')
  const [offset, setOffset] = useState(0)
  const [next, setNext] = useState<number | null>(null)
  const [revision, setRevision] = useState(0)
  const [modal, setModal] = useState<{ mode: Mode; market?: Market } | null>(null)
  const [pending, setPending] = useState<Pending | null>(null)
  const [busy, setBusy] = useState(false)
  const [clock, setClock] = useState(Date.now() / 1000)
  const inFlight = useRef(false)
  useEffect(() => { const timer = setInterval(() => setClock(Date.now() / 1000), 1000); return () => clearInterval(timer) }, [])
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true); setError('')
    const path = marketId ? `/${marketId}` : `?${new URLSearchParams({ status, q: query, offset: String(offset), ...dateBounds(appliedDates) })}`
    api(path, { signal: controller.signal }).then(data => {
      if (controller.signal.aborted) return
      setAnonymous(false); setSession({ userId: data.userId, balance: data.balance, csrfToken: data.csrfToken })
      setMarkets(previous => marketId ? [data.market] : offset ? [...previous, ...data.markets] : data.markets)
      setNext(data.nextOffset ?? null)
      try { setPending(JSON.parse(sessionStorage.getItem(`prediction-pending:${data.userId}`) || 'null')) } catch { /* Optional browser storage. */ }
    }).catch(cause => { if (!controller.signal.aborted) { setError(cause.message); setAnonymous(cause instanceof ApiError && cause.status === 401); setMarkets([]) } })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [marketId, status, query, offset, revision, appliedDates])
  useEffect(() => {
    if (!session?.userId) return
    const controller = new AbortController()
    api('/permissions', { signal: controller.signal }).then(data => {
      if (!controller.signal.aborted) { setPermissions(data); setPermissionError('') }
    }).catch(() => { if (!controller.signal.aborted) { setPermissions({ canManage: false, canSponsor: false }); setPermissionError('管理權限暫時無法驗證。') } })
    return () => controller.abort()
  }, [session?.userId, revision])

  /** Fetch the latest version before editing, resolving, or confirming a stake. */
  async function open(mode: Mode, market?: Market) {
    if (pending || inFlight.current) return
    setError('')
    if (!market) { setModal({ mode }); return }
    inFlight.current = true; setBusy(true)
    try {
      const data = await api(`/${market.id}`)
      setSession({ userId: data.userId, balance: data.balance, csrfToken: data.csrfToken })
      setModal({ mode, market: data.market })
    } catch (cause) { setError(cause instanceof Error ? cause.message : '讀取失敗。') }
    finally { inFlight.current = false; setBusy(false) }
  }

  /** Persist one exact command across network failures and refresh the displayed totals. */
  async function submit(intent: Intent | Pending) {
    if (!session || inFlight.current) return
    const command: Pending = 'requestId' in intent ? intent : { ...intent, requestId: crypto.randomUUID() }
    const key = `prediction-pending:${session.userId}`
    inFlight.current = true; setBusy(true); setPending(command); setModal(null); setError(''); setMessage('')
    try { sessionStorage.setItem(key, JSON.stringify(command)) } catch { /* In-page retries remain idempotent. */ }
    try {
      const data = await api(command.path, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': session.csrfToken }, body: JSON.stringify({ ...command.body, requestId: command.requestId }) })
      try { sessionStorage.removeItem(key) } catch { /* Optional storage. */ }
      setPending(null); setMessage('操作已完成。'); setOffset(0); setRevision(value => value + 1)
      window.dispatchEvent(new Event('shards-changed'))
      if (command.path === '') navigate(`/predictions/${data.market.id}`)
    } catch (cause) {
      if (cause instanceof ApiError && cause.status >= 400 && cause.status < 500) {
        try { sessionStorage.removeItem(key) } catch { /* Optional storage. */ }
        setPending(null)
      }
      setError(cause instanceof Error ? cause.message : '連線失敗，請重試相同操作。')
    } finally { inFlight.current = false; setBusy(false) }
  }

  const disabled = loading || busy || Boolean(pending)
  return <section className="prediction-page">
    <Link className="profile-back" to={marketId ? '/predictions' : '/'}><ArrowLeft size={16} />{marketId ? '返回預測列表' : '返回功能導覽'}</Link>
    <header className="prediction-heading"><div><h1>預測系統</h1><p>星之碎片 · 比例分配預測池</p></div><div className="prediction-wallet"><img src={shardIcon} alt="星之碎片" />{session?.balance.toLocaleString() ?? '—'}</div></header>
    <div className="prediction-toolbar">{!marketId && <form className="prediction-filters" onSubmit={event => {
      event.preventDefault()
      if (!dates.start || !dates.end || dates.start > dates.end) { setDateError('起始日期不得晚於結束日期。'); return }
      setDateError(''); setOffset(0); setQuery(search); setAppliedDates({ ...dates }); setRevision(value => value + 1)
    }}>
      <label className="prediction-search">名稱<input aria-label="搜尋預測盤" placeholder="搜尋預測盤" maxLength={120} value={search} onChange={event => setSearch(event.target.value)} /></label>
      <div className="prediction-status-filter"><label htmlFor="prediction-status">狀態</label><Select inputId="prediction-status" aria-label="預測盤狀態" options={statusOptions} value={statusOptions.find(option => option.value === status)} isSearchable={false} onChange={option => { if (option) { setStatus(option.value); setOffset(0) } }} styles={{ container: base => ({ ...base, width: '100%', minWidth: 0 }), control: base => ({ ...base, minHeight: 42, borderRadius: 6, borderColor: '#bcc9cd' }), valueContainer: base => ({ ...base, minWidth: 0 }), menu: base => ({ ...base, zIndex: 20 }) }} /></div>
      <fieldset className="prediction-date-range"><legend>最後押注日期</legend><label>起始日期<input type="date" required value={dates.start} onChange={event => setDates(previous => ({ ...previous, start: event.target.value }))} /></label><label>結束日期<input type="date" required min={dates.start || undefined} value={dates.end} onChange={event => setDates(previous => ({ ...previous, end: event.target.value }))} /></label></fieldset>
      <button type="submit" title="搜尋" aria-label="搜尋"><Search size={18} />搜尋</button>
      {dateError && <p className="prediction-error prediction-date-error" role="alert">{dateError}</p>}
    </form>}
      <div className="prediction-actions"><button className="prediction-icon" title="重新整理" aria-label="重新整理" disabled={busy} onClick={() => { setOffset(0); setRevision(value => value + 1) }}><RefreshCw size={18} /></button>{permissions.canManage && <button className="prediction-primary" disabled={disabled} onClick={() => open('create')}><Plus size={17} />建立預測盤</button>}</div>
    </div>
    {permissionError && <p className="prediction-muted">{permissionError}</p>}
    {anonymous && <p><a href="/api/auth/discord/login">登入後查看預測盤</a></p>}
    {/* {error && <p className="prediction-error" role="alert">{error}</p>}{message && <p role="status">{message}</p>} */}
    {pending && <div className="prediction-pending"><p>{pending.summary}</p><button disabled={busy} onClick={() => submit(pending)}><RefreshCw size={17} />{busy ? '處理中…' : '重試確認結果'}</button></div>}
    {loading && <p role="status">載入預測盤中…</p>}
    {!loading && !error && markets.length === 0 && <p className="prediction-empty">目前沒有預測盤。</p>}
    <div className={`prediction-list ${marketId ? 'is-detail' : ''}`}>{markets.map(market => {
      const openNow = market.status === 'active' && clock < market.closesAt
      const phase = market.status === 'active' ? openNow ? 'open' : clock < market.settlesAt ? 'closed' : 'awaiting_result' : market.status
      return <article className="prediction-market" key={market.id}>
        <div className="prediction-market-title"><h2>{marketId ? market.name : <Link to={`/predictions/${market.id}`}>{market.name}</Link>}</h2><span className={`prediction-phase phase-${phase}`}>{phaseLabels[phase]}</span></div>
        {market.description && <p className="prediction-description">{market.description}</p>}
        <dl className="prediction-times"><div><dt><Clock size={14} />最後押注時間</dt><dd>{formatTime(market.closesAt)}</dd></div><div><dt>結算時間</dt><dd>{formatTime(market.settlesAt)}</dd></div></dl>
        <div className="prediction-pool"><span>獎池 <strong>{market.pool.toLocaleString()}</strong></span><span>基礎獎勵 <strong>{market.baseReward.toLocaleString()}</strong></span></div>
        <table><thead><tr><th>選項</th><th>押注總額</th><th>當前賠率</th></tr></thead><tbody>{market.options.map(option => <tr key={option.id} className={market.winnerId === option.id ? 'is-winner' : ''}><td>{market.winnerId === option.id && <Trophy size={15} aria-label="獲勝" />}{option.label}{option.ownAmount > 0 && <small>你的押注 {option.ownAmount.toLocaleString()}</small>}</td><td>{option.total.toLocaleString()}</td><td>{odds(option.odds)}</td></tr>)}</tbody></table>
        <p className="prediction-muted">賠率含本金，依結算時池額計算。</p>
        {market.status !== 'active' && <p className="prediction-settled">{market.settlementMode === 'refund' ? '本盤已退款，基礎獎勵未派發。' : '本盤已完成比例分配。'}你的下注 {market.ownAmount.toLocaleString()} · 領回 {market.ownPayout.toLocaleString()}</p>}
        <div className="prediction-actions">{openNow && <button className="prediction-primary" disabled={disabled || !session || session.balance < 1} onClick={() => open('bet', market)}><Plus size={17} />押注</button>}{permissions.canManage && market.status === 'active' && <><button disabled={disabled} onClick={() => open('edit', market)}><Edit3 size={16} />編輯</button><button disabled={disabled || clock < market.settlesAt} onClick={() => open('settle', market)}><Trophy size={16} />公布結果</button><button disabled={disabled} onClick={() => open('cancel', market)}><X size={16} />取消預測盤</button></>}</div>
      </article>
    })}</div>
    {!marketId && next !== null && <button disabled={loading || busy} onClick={() => setOffset(next)}>載入更多</button>}
    <section className="prediction-rules"><h2><ShieldCheck size={18} />分配規則</h2><p>押注扣除星之碎片，截止後不再接受下注；由管理員於結算時間後公布獲勝選項。獲勝者按各自押中金額比例分配全池（含本金與基礎獎勵），不收取手續費。</p><p>沒有對手盤且無基礎獎勵時，押中者領回本金；有基礎獎勵仍按比例分配。無人押中或預測盤取消時，退還所有下注，基礎獎勵不派發。整數餘額採最大餘數法分配，同餘數依使用者 ID 排序。</p><p>選項建立後不可更改，基礎獎勵只能增加。時間顯示於你的時區：{Intl.DateTimeFormat().resolvedOptions().timeZone}。</p></section>
    {modal && <MarketDialog key={`${modal.mode}:${modal.market?.id}`} {...modal} sponsor={permissions.canSponsor} balance={session?.balance || 0} locked={busy} onClose={() => setModal(null)} onSubmit={submit} />}
  </section>
}
