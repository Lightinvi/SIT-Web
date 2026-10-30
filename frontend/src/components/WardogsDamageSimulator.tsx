import { useState } from 'react'
import { Link } from 'react-router-dom'
import { HIT_ZONES, simulateHit } from '../utils/wardogsDamage'
import type { DamageModel } from '../utils/wardogsDamage'

const paths: Record<string, string[]> = {
  Head: ['M49 6 L66 6 L72 17 L70 37 L63 43 L51 40 L45 28 L45 16 Z'],
  Neck: ['M52 42 L64 43 L66 52 L51 52 Z'],
  'Torso.Upper': ['M38 52 L77 52 L82 77 L34 77 Z'],
  'Torso.Middle': ['M34 79 L82 79 L79 98 L37 98 Z'],
  'Torso.Lower': ['M37 100 L79 100 L82 117 L34 117 Z'],
  Pelvis: ['M34 119 L82 119 L76 139 L58 147 L40 139 Z'],
  'Arm.Upper': ['M24 56 L35 53 L32 86 L20 89 L17 77 Z', 'M80 53 L92 56 L98 77 L94 89 L84 86 Z'],
  'Arm.Lower': ['M20 91 L32 88 L28 116 L17 120 L14 109 Z', 'M84 88 L95 91 L101 109 L98 120 L87 116 Z'],
  'Arm.Hand': ['M17 122 L27 119 L26 139 L21 146 L16 138 Z', 'M88 119 L98 122 L99 138 L94 146 L89 139 Z'],
  'Leg.Thigh': ['M39 143 L56 150 L54 189 L37 189 L34 170 Z', 'M60 150 L77 143 L82 170 L78 189 L61 189 Z'],
  'Leg.Calf': ['M37 192 L54 192 L51 232 L39 232 L35 209 Z', 'M61 192 L78 192 L80 209 L75 232 L63 232 Z'],
  'Leg.Foot': ['M39 235 L51 235 L51 248 L32 248 L32 243 Z', 'M63 235 L75 235 L82 243 L82 248 L63 248 Z'],
}
const fmt = (number: number) => Number(number.toFixed(2)).toLocaleString()
export default function WardogsDamageSimulator({ model }: { model: DamageModel }) {
  const [ammoId, setAmmoId] = useState(model.ammo[0]?.id ?? '')
  const [helmetId, setHelmetId] = useState('')
  const [armorId, setArmorId] = useState('')
  const [zone, setZone] = useState<string>('Head')
  const ammo = model.ammo.find(item => item.id === ammoId) ?? model.ammo[0]
  const helmet = model.armor.find(item => item.id === helmetId)
  const armor = model.armor.find(item => item.id === armorId)
  const results = ammo ? HIT_ZONES.map(([key, label]) => ({ key, label, result: simulateHit(model, ammo, key, 0, helmet, armor) })) : []
  const selected = results.find(row => row.key === zone)
  return <section className="wardogs-damage-panel" aria-labelledby="damage-title">
    <h2 id="damage-title">命中部位與射擊模擬</h2>
    <p className="wardogs-simulation-summary">以近距離（0 m）、100 HP 目標估算，選擇彈藥與防護後點選命中部位。</p>
    <div className="wardogs-protection-controls">
      <label>使用彈藥<select value={ammo?.id ?? ''} onChange={event => setAmmoId(event.target.value)}>{model.ammo.map(item => <option value={item.id} key={item.id}>{item.name} · {item.ammoType}</option>)}</select></label>
      {(['Helmet', 'Armor'] as const).map(slot => <label key={slot}>{slot === 'Helmet' ? '頭盔' : '護甲'}<select value={slot === 'Helmet' ? helmetId : armorId} onChange={event => slot === 'Helmet' ? setHelmetId(event.target.value) : setArmorId(event.target.value)}><option value="">無防護</option>{model.armor.filter(item => item.slot === slot).map(item => <option value={item.id} key={item.id}>{item.name}（{item.reduction}%）</option>)}</select></label>)}
    </div>
    {!ammo ? <p>來源未提供可確認的相容彈藥。</p> : <>
      <p><Link to={`/wardogs/database/items/${encodeURIComponent(ammo.id)}`}>查看 {ammo.name} 詳細資料 →</Link></p>
      <div className="wardogs-hit-layout">
        <div className="wardogs-hit-body"><svg viewBox="0 0 116 260" role="group" aria-label="選擇命中部位">{HIT_ZONES.map(([key, label]) => <g key={key} role="button" tabIndex={0} aria-label={label} aria-pressed={zone === key} onClick={() => setZone(key)} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setZone(key) } }} className={zone === key ? 'selected' : ''}>{paths[key].map((path, index) => <path key={index} d={path} />)}<title>{label}</title></g>)}</svg>
          <strong>{selected?.label}</strong><span>{selected?.result ? `${fmt(selected.result.effective)} 傷害` : '無法估算'}</span>
        </div>
        <div className="wardogs-hit-table"><table><caption>100 HP 目標，各部位單發直擊估算</caption><thead><tr><th>部位</th><th>倍率</th><th>原始傷害</th><th>有效傷害</th><th>致死發數</th><th>TTK</th><th>防護</th></tr></thead><tbody>{results.map(({ key, label, result }) => <tr key={key} className={zone === key ? 'selected' : ''}><th scope="row"><button type="button" onClick={() => setZone(key)} aria-pressed={zone === key}>{label}</button></th><td>{result ? `${fmt(result.multiplier)}×` : '—'}</td><td>{result ? fmt(result.raw) : '—'}</td><td>{result ? <strong>{fmt(result.effective)}</strong> : '—'}</td><td>{result?.shots ?? '—'}</td><td>{result?.ttk !== null && result?.ttk !== undefined ? `${result.ttk.toFixed(2)} s` : '—'}</td><td>{result?.armor?.name ?? '無防護'}</td></tr>)}</tbody></table></div>
      </div>
      {selected?.result && <p className="wardogs-shot-formula">{selected.label}：基礎 {fmt(selected.result.base)} × 部位 {fmt(selected.result.multiplier)} × 規則 {fmt(selected.result.plain)} × 防護 {fmt(selected.result.protection)} ＝ <strong>{fmt(selected.result.effective)} 傷害</strong></p>}
      <p className="wardogs-simulation-note">估算以同版本資料及完整護甲階段計算，僅在實際覆蓋部位套用防護。TTK 從第一發命中起，以射速計算理想連射，不計點放間隔、換彈、護甲耗損、技能、穿透與飛行減速；霰彈為單顆彈丸，爆炸傷害不估算。部分遊戲自訂口徑修正未公開。</p>
    </>}
    <h3>相容彈藥</h3><div className="wardogs-ammo-links">{model.ammo.map(item => <Link key={item.id} to={`/wardogs/database/items/${encodeURIComponent(item.id)}`}><strong>{item.name}</strong><span>{item.ammoType}</span></Link>)}</div>
    <p className="wardogs-simulation-note">模型參考：<a href="https://github.com/warpuppies/wardogs-data/blob/main/data/README.md" target="_blank" rel="noreferrer">來源資料定義</a> · <a href="https://kiyogitpy.github.io/wardogs-data-docs/pipelines/Wardogs_DamagePipeline_v2.html" target="_blank" rel="noreferrer">傷害流程分析</a></p>
  </section>
}
