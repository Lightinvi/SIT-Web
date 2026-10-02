/** Server-authoritative blackjack with recoverable commands and sprite-card animation. */
import { useEffect, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeft, CopyPlus, Hand, Layers, Play, Plus, RefreshCw, ShieldCheck, ShieldOff } from 'lucide-react'
import shardIcon from '../assets/star_shard.png'
import './Blackjack.css'

type Card = { id: string; face: string }
type GameHand = { cards: Card[]; bet: number; total: number; done: boolean; result?: string; payout?: number }
type Round = { id: string; version: number; phase: string; hands: GameHand[]; dealer: (Card | null)[]; dealerTotal: number; activeHand: number; baseBet: number; insurance: number; insurancePayout?: number; staked: number; payout?: number; net?: number; actions: string[] }
type State = { userId: string; csrfToken: string; balance: number; round: Round | null }
type Command = { requestId: string; action: string; bet?: number; roundId?: string; version?: number }
const rankNames = ['A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K']
const suits = ['C', 'D', 'H', 'S']
const suitNames = ['梅花', '方塊', '紅心', '黑桃']
const results: Record<string, string> = { win: '勝利', lose: '落敗', push: '平手', bust: '爆牌', blackjack: 'Blackjack' }
const controls = [
  { action: 'hit', label: '要牌', Icon: Plus }, { action: 'stand', label: '停牌', Icon: Hand },
  { action: 'double', label: '加倍', Icon: CopyPlus }, { action: 'split', label: '分牌', Icon: Layers },
  { action: 'insurance', label: '購買保險', Icon: ShieldCheck }, { action: 'decline', label: '不買保險', Icon: ShieldOff },
]

/** Position one of 52 faces or the blue back in the provided 13-by-5 sprite sheet. */
function PlayingCard({ card, delay = 0 }: { card: Card | null; delay?: number }) {
  const rank = card ? rankNames.indexOf(card.face.slice(0, -1)) : 2
  const suit = card ? suits.indexOf(card.face.slice(-1)) : 4
  const style = { '--card-x': `${rank / 12 * 100}%`, '--card-y': `${suit / 4 * 100}%`, '--deal-delay': `${delay}ms` } as CSSProperties
  return <div className="bj-card" style={style} role="img" aria-label={card ? `${suitNames[suit]} ${card.face.slice(0, -1)}` : '暗牌'}>
    <div className={`bj-card-flip ${card ? 'is-face-up' : ''}`}><div className="bj-card-back" /><div className="bj-card-face" /></div>
  </div>
}

/** Display a personal table while all dealing and shard accounting run on the server. */
export default function Blackjack() {
  const [state, setState] = useState<State | null>(null)
  const [bet, setBet] = useState('10')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [animating, setAnimating] = useState(false)
  const [error, setError] = useState('')
  const [anonymous, setAnonymous] = useState(false)
  const [pending, setPending] = useState<Command | null>(null)
  const [attempt, setAttempt] = useState(0)
  const inFlight = useRef(false)
  const alive = useRef(true)
  const animationTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => {
    alive.current = true
    return () => { alive.current = false; if (animationTimer.current) clearTimeout(animationTimer.current) }
  }, [])
  useEffect(() => {
    const controller = new AbortController()
    const timeout = window.setTimeout(() => controller.abort(), 15000)
    setLoading(true)
    fetch('/api/blackjack', { signal: controller.signal, cache: 'no-store' })
      .then(async response => {
        if (response.status === 401) { setAnonymous(true); setState(null); return }
        const data = await response.json()
        if (!response.ok) throw new Error(data.error || '無法載入牌局。')
        if (controller.signal.aborted) return
        setAnonymous(false); setState(data); setError('')
        try { setPending(JSON.parse(sessionStorage.getItem(`blackjack-pending:${data.userId}`) || 'null')) } catch { setPending(null) }
      }).catch(cause => { if (alive.current) setError(cause instanceof Error ? cause.message : '連線失敗，請重試。') })
      .finally(() => { clearTimeout(timeout); if (alive.current) setLoading(false) })
    return () => { controller.abort(); clearTimeout(timeout) }
  }, [attempt])

  /** Reuse uncertain commands across retries and reloads; never repeat a debit blindly. */
  async function send(action: string, retry?: Command) {
    if (!state || inFlight.current || animating || (pending && !retry)) return
    const command: Command = retry || { requestId: crypto.randomUUID(), action,
      ...(action === 'start' ? { bet: Number(bet) } : { roundId: state.round?.id, version: state.round?.version }) }
    inFlight.current = true; setBusy(true); setError(''); setPending(command)
    const key = `blackjack-pending:${state.userId}`
    try { sessionStorage.setItem(key, JSON.stringify(command)) } catch { /* Server receipts still protect in-page retries. */ }
    const controller = new AbortController()
    const timeout = window.setTimeout(() => controller.abort(), 20000)
    try {
      const response = await fetch('/api/blackjack', { method: 'POST', signal: controller.signal,
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': state.csrfToken }, body: JSON.stringify(command) })
      const data = await response.json()
      if (!response.ok) {
        if (response.status >= 400 && response.status < 500) {
          try { sessionStorage.removeItem(key) } catch { /* Optional browser storage. */ }
          if (alive.current) setPending(null)
        }
        throw new Error(data.error || '操作尚未確認，請重試同一操作。')
      }
      try { sessionStorage.removeItem(key) } catch { /* Optional browser storage. */ }
      window.dispatchEvent(new Event('shards-changed'))
      if (!alive.current) return
      setPending(null); setState(data)
      const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches
      setAnimating(!reduced)
      if (animationTimer.current) clearTimeout(animationTimer.current)
      const cardCount = Math.max(data.round?.dealer.length || 0, ...data.round.hands.map((item: GameHand) => item.cards.length))
      animationTimer.current = setTimeout(() => { if (alive.current) setAnimating(false) }, reduced ? 0 : 750 + cardCount * 140)
    } catch (cause) {
      if (alive.current) setError(cause instanceof Error && cause.name !== 'AbortError' ? cause.message : '連線中斷，請重試以確認操作結果。')
    } finally { clearTimeout(timeout); inFlight.current = false; if (alive.current) setBusy(false) }
  }

  const round = state?.round
  const settled = round?.phase === 'settled'
  const locked = loading || busy || animating || Boolean(pending)
  const amount = Number(bet)
  const validBet = Number.isSafeInteger(amount) && amount >= 2 && amount % 2 === 0 && amount <= (state?.balance || 0)
  return <section className="blackjack-page">
    <Link to="/" className="profile-back"><ArrowLeft size={16} />返回功能導覽</Link>
    <header className="bj-heading"><div><h1>21 點</h1><p>BLACKJACK · 美式規則 · 1 對 1</p></div></header>
    <div className="bj-topline"><span><Layers size={16} />全站共用牌堆 · 5 副 / 260 張</span></div>
    {loading && <p role="status">載入牌局中…</p>}
    {anonymous && <p className="bj-notice"><a href="/api/auth/discord/login">登入後遊玩</a></p>}
    {error && <div className="bj-notice" role="alert"><span>{error}</span>{pending ? <button disabled={busy} onClick={() => send(pending.action, pending)}><RefreshCw size={16} />重試操作</button> : <button disabled={busy} onClick={() => setAttempt(value => value + 1)}><RefreshCw size={16} />重新確認</button>}</div>}
    {pending && !busy && !error && <div className="bj-notice"><span>有一筆操作等待確認。</span><button onClick={() => send(pending.action, pending)}><RefreshCw size={16} />確認操作</button></div>}
    <div className="bj-table" aria-label="21 點牌桌" aria-busy={busy || animating}>
      <div className="bj-deck" aria-hidden="true"><PlayingCard card={null} /><span>SHOE / 5 DECKS</span></div>
      <section className="bj-dealer"><h2>莊家 <span>{round ? round.dealerTotal : '—'} 點{round && !settled && '（明牌）'}</span></h2><div className="bj-cards">{round ? round.dealer.map((card, index) => <PlayingCard key={`${round.id}:dealer:${index}`} card={card} delay={index * 140} />) : <><PlayingCard card={null} /><PlayingCard card={null} delay={140} /></>}</div></section>
      <div className="bj-table-mark" aria-hidden="true">BLACKJACK<span>Star Impact Team</span></div>
      <div className="bj-hands">{round ? round.hands.map((item, index) => <section key={`${round.id}:${index}`} className={`bj-player-hand ${!settled && round.activeHand === index ? 'is-active' : ''}`}>
        <h2>{round.hands.length > 1 ? `手牌 ${index + 1}` : '你的手牌'} <span>{item.total} 點</span></h2>
        <div className="bj-cards">{item.cards.map((card, cardIndex) => <PlayingCard key={card.id} card={card} delay={cardIndex * 140} />)}</div>
        <p>下注 {item.bet.toLocaleString()}{item.result && !animating ? ` · ${results[item.result]} · 領回 ${item.payout}` : item.done && !settled ? ' · 已停牌' : ''}</p>
      </section>) : <div className="bj-waiting"><span>21</span><p>等待下注</p></div>}</div>
    </div>
    <div className="bj-controls">
      <div className="bj-result" role="status" aria-live="polite">{busy || animating ? '發牌中…' : settled ? <><strong>{(round.net || 0) > 0 ? '+' : ''}{round.net} 星之碎片</strong><span>總下注 {round.staked} · 領回 {round.payout}{round.insurance > 0 ? ` · 保險領回 ${round.insurancePayout}` : ''}</span></> : round?.phase === 'insurance' ? `莊家明牌為 A · 保險 ${round.baseBet / 2} 點` : round ? '輪到你了' : '每注最低 2 點，以偶數下注'}</div>
      {state && (!round || settled) && <form className="bj-bet-form" onSubmit={event => { event.preventDefault(); if (validBet) void send('start') }}><label>下注星之碎片<input type="number" inputMode="numeric" min={2} max={state.balance} step={2} value={bet} disabled={locked} onChange={event => setBet(event.target.value)} /></label><button className="bj-primary" type="submit" disabled={locked || !validBet}><Play size={18} />{round ? '再玩一局' : '下注發牌'}</button>{!validBet && <small>請輸入不超過餘額的正偶數。</small>}</form>}
      {state && round && !settled && <div className="bj-actions">{controls.filter(control => round.phase === 'insurance' ? ['insurance', 'decline'].includes(control.action) : !['insurance', 'decline'].includes(control.action)).map(({ action, label, Icon }) => <button key={action} disabled={locked || !round.actions.includes(action)} onClick={() => send(action)}><Icon size={18} />{label}</button>)}</div>}
    </div>
    <section className="bj-rules" aria-labelledby="bj-rules-title"><h2 id="bj-rules-title">美式規則與賠付</h2>
      <ul><li>玩家與系統莊家一對一。全站所有玩家與莊家共用 5 副標準撲克牌，共 260 張，不含鬼牌；隨機洗牌後依序發出，全部發完才洗下一套，可能在牌局中途換套。</li>
        <li>A 計 1 或 11 點；J、Q、K 計 10 點。超過 21 點為爆牌，玩家爆牌立即輸掉該手。莊家未滿 17 點必須補牌，包含 soft 17 在內的 17 點以上停牌。</li>
        <li>莊家開局持一張明牌與一張暗牌。明牌為 A 時先提供保險，再檢查 Blackjack；明牌為 10 點牌時先檢查 Blackjack，玩家才可操作。</li>
        <li>一般勝局含本金領回下注的 2 倍；平手退還本金。原始兩張 A 加 10 點牌為 Blackjack，賠 3:2，含本金領回 2.5 倍；雙方 Blackjack 平手。</li>
        <li>保險費固定為原下注 50%，另行扣款且須有足夠餘額。莊家 Blackjack 才贏保險，賠 2:1，含保險本金領回保險金的 3 倍；否則保險金歸零。</li>
        <li>前兩張可加倍：追加相同下注，只補一張後停牌。兩張相同點數可分牌，最多 4 手，每次追加相同下注，分牌後可加倍。分 A 各只補一張並停牌，不可再次分 A。</li>
        <li>分牌後 21 點不算 Blackjack，按一般勝局結算。不提供投降或五張牌自動獲勝。下注限至少 2 點的正偶數，不可超過餘額。</li>
        <li>離開或重新整理不會取消已下注牌局，重新進入可繼續。星之碎片扣款與結算可在碎片紀錄查閱。</li></ul>
    </section>
  </section>
}
