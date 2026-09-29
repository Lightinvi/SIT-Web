/** Animated daily rewards with server-owned eligibility, prize selection, and ledger writes. */
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeft, Disc3, History, RefreshCw } from 'lucide-react'
import { Wheel } from 'spin-wheel'
import { spinnerRequest } from '../api/spinner'
import type { SpinnerPrize, SpinnerReceipt, SpinnerState, SpinResponse } from '../api/spinner'
import shardIcon from '../assets/star_shard.png'
import './DailySpinner.css'

const colors = ['#517fbd', '#217f72', '#bc4c68', '#7857a2', '#b67b18']

/** Render a canvas wheel and recover committed results after retries or page reloads. */
export default function DailySpinner() {
  const [data, setData] = useState<SpinnerState | null>(null)
  const [result, setResult] = useState<SpinnerReceipt | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [spinning, setSpinning] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const [seconds, setSeconds] = useState(0)
  const host = useRef<HTMLDivElement>(null)
  const wheel = useRef<Wheel | null>(null)
  const busy = useRef(false)
  const alive = useRef(false)
  const deadline = useRef(0)
  const requestId = useRef('')
  const dataRef = useRef<SpinnerState | null>(null)
  const heading = useRef<HTMLHeadingElement>(null)
  const signature = data ? JSON.stringify(data.prizes) : ''

  useEffect(() => {
    alive.current = true
    heading.current?.focus(); window.scrollTo(0, 0)
    return () => { alive.current = false }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    let refreshing = false
    /** Refresh at server midnight and window focus, without interrupting an active draw. */
    async function refresh() {
      if (refreshing || busy.current) return
      refreshing = true
      try {
        const state = await spinnerRequest<SpinnerState>('', { signal: controller.signal })
        if (controller.signal.aborted || busy.current) return
        dataRef.current = state
        deadline.current = performance.now() + Math.max(0, state.nextResetAt - state.serverTime) * 1000
        setSeconds(Math.ceil((deadline.current - performance.now()) / 1000))
        setData(state); setResult(state.todaySpin); setError('')
      } catch (cause) {
        if (!controller.signal.aborted) setError(cause instanceof Error && cause.name === 'Error' ? cause.message : '連線逾時，請重試。')
      } finally { refreshing = false; if (!controller.signal.aborted) setLoading(false) }
    }
    void refresh()
    const timer = window.setInterval(() => {
      const remaining = Math.max(0, Math.ceil((deadline.current - performance.now()) / 1000))
      setSeconds(remaining)
      if (deadline.current && remaining === 0) void refresh()
    }, 1000)
    window.addEventListener('focus', refresh)
    return () => { controller.abort(); window.clearInterval(timer); window.removeEventListener('focus', refresh) }
  }, [attempt])

  useEffect(() => {
    if (!host.current || !signature) return
    const prizes: SpinnerPrize[] = JSON.parse(signature)
    const instance = new Wheel(host.current, {
      items: prizes.map(prize => ({ label: `${prize.multiplier}x` })),
      isInteractive: false, pointerAngle: 0, radius: 0.94,
      itemBackgroundColors: colors, itemLabelColors: ['#ffffff'],
      itemLabelFont: 'sans-serif', itemLabelFontSizeMax: 36,
      itemLabelAlign: 'center', itemLabelRadius: 0.7,
      borderColor: '#263e45', borderWidth: 5, lineColor: '#ffffff', lineWidth: 2,
      onRest: () => { if (alive.current) { busy.current = false; setSpinning(false) } },
    })
    wheel.current = instance
    return () => { instance.remove(); wheel.current = null }
  }, [signature])

  useEffect(() => {
    if (!result || busy.current || !wheel.current || !signature) return
    const prizes: SpinnerPrize[] = JSON.parse(signature)
    const index = prizes.findIndex(prize => prize.multiplier === result.multiplier)
    if (index >= 0) wheel.current.spinToItem(index, 0, true, 0)
  }, [result, signature])

  /** Keep an uncertain request ID across reloads, including retries after midnight. */
  async function draw() {
    const current = dataRef.current
    if (!current?.authenticated || !current.canSpin || busy.current || !wheel.current) return
    busy.current = true; setSpinning(true); setError('')
    const key = `daily-spinner-pending:${current.userId}`
    try {
      try { requestId.current ||= sessionStorage.getItem(key) || '' } catch { /* Storage may be disabled. */ }
      requestId.current ||= crypto.randomUUID()
      try { sessionStorage.setItem(key, requestId.current) } catch { /* In-memory retries remain safe. */ }
      const response = await spinnerRequest<SpinResponse>('/spin', {
        method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': current.csrfToken || '' },
        body: JSON.stringify({ requestId: requestId.current }),
      })
      try { sessionStorage.removeItem(key) } catch { /* Storage is optional. */ }
      requestId.current = ''
      window.dispatchEvent(new Event('shards-changed'))
      if (!alive.current) return
      dataRef.current = response
      deadline.current = performance.now() + Math.max(0, response.nextResetAt - response.serverTime) * 1000
      setData(response); setResult(response.result)
      const index = response.prizes.findIndex(prize => prize.multiplier === response.result.multiplier)
      const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
      wheel.current?.spinToItem(index, reducedMotion ? 0 : 4800, true, reducedMotion ? 0 : 6)
      if (reducedMotion) { busy.current = false; setSpinning(false) }
    } catch (cause) {
      if (alive.current) {
        busy.current = false; setSpinning(false)
        setError(cause instanceof Error && cause.name === 'Error' ? cause.message : '連線中斷，請重試以確認本次結果。')
      }
    }
  }

  const countdown = [Math.floor(seconds / 3600), Math.floor(seconds / 60) % 60, seconds % 60].map(value => String(value).padStart(2, '0')).join(':')
  const localTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone
  const localDateTime = new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' })
  return <section className="daily-spinner" aria-labelledby="spinner-title">
    <Link to="/" className="spinner-back"><ArrowLeft size={17} />返回功能選項</Link>
    <header className="spinner-heading"><div><h1 id="spinner-title" tabIndex={-1} ref={heading}>每日轉盤</h1><p>每日一次 · 伺服器時間 00:00 重置</p>
      {data && <p>下次重置：<time dateTime={new Date(data.nextResetAt * 1000).toISOString()}>{localDateTime.format(new Date(data.nextResetAt * 1000))}</time>（{localTimezone}）</p>}
    </div><Link to="/star-shards"><History size={17} />碎片紀錄</Link></header>
    {loading && <p role="status">載入轉盤中…</p>}
    {error && <div className="spinner-error" role="alert">{error}<button disabled={spinning} onClick={() => { setError(''); setAttempt(value => value + 1) }}><RefreshCw size={16} />重新確認</button></div>}
    <div className="spinner-layout">
      <div className="spinner-play">
        <div className="spinner-wheel-wrap">
          <div className="spinner-pointer" aria-hidden="true" />
          <div className="spinner-wheel" ref={host} role="img" aria-label="星之碎片獎勵轉盤：0.5、1、2、2.5、5 倍" />
          <div className="spinner-hub" aria-hidden="true"><img src={shardIcon} alt="" /></div>
        </div>
        <div className="spinner-result" role="status" aria-live="polite">
          {spinning ? <p>轉盤進行中…</p> : result ? <><strong>+{result.reward} <span>星之碎片</span></strong><p>{result.multiplier}x · 獎勵已入帳</p><p><time dateTime={new Date(result.createdAt * 1000).toISOString()}>{localDateTime.format(new Date(result.createdAt * 1000))}</time></p></> : <p>基礎獎勵 <strong>{data?.baseReward ?? 10}</strong> 星之碎片</p>}
        </div>
        {data?.authenticated ? <button className="spinner-start" disabled={loading || spinning || !data.canSpin} onClick={draw}><Disc3 size={20} />{spinning ? '轉動中…' : data.canSpin ? '轉動轉盤' : '今日已領取'}</button> : !loading && <a className="spinner-start" href="/api/auth/discord/login">登入後轉動</a>}
        {data && <p className="spinner-countdown">距離下次重置 <time>{countdown}</time></p>}
      </div>
      <aside className="spinner-odds" aria-labelledby="spinner-odds-title">
        <h2 id="spinner-odds-title">獎勵機率</h2>
        <table><thead><tr><th>倍率</th><th>星之碎片</th><th>機率</th></tr></thead><tbody>
          {data?.prizes.map((prize, index) => <tr key={prize.multiplier}><td><span className="spinner-swatch" style={{ backgroundColor: colors[index] }} />{prize.multiplier}x</td><td>{prize.reward}</td><td>{prize.probability}%</td></tr>)}
        </tbody></table>
        <p>每日免費轉動一次，獎勵自動加入星之碎片餘額。</p>
        <p>轉盤扇區為等分示意，實際中獎機率以上表為準。</p>
      </aside>
    </div>
  </section>
}
