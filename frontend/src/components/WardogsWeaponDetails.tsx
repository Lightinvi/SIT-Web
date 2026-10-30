import { useId, useState } from 'react'
import { recoilPath } from '../utils/wardogsRecoil'
import type { RecoilPoint } from '../utils/wardogsRecoil'

type Weapon = {
  rpm?: number; fireModes?: string[]; calibers?: string[]; muzzleVelocity?: number; effectiveRange?: number;
  damageFalloff?: { distance: number; multiplier: number }[]; randomDeviation?: number; accuracy?: number; meleeDamage?: number; suppressionMultiplier?: number;
  recoil?: { pattern?: RecoilPoint[]; patternResetTime?: number; viewKickMultiplier?: number; afterPatternPitch?: number[]; afterPatternYaw?: number[] }
}
const modes: Record<string, string> = { SemiAutomatic: '半自動', Automatic: '全自動', FullAutomatic: '全自動', Burst: '點放', BoltAction: '栓動', Single: '單發' }

export default function WardogsWeaponDetails({ weapon }: { weapon?: Weapon }) {
  return <section className="wardogs-weapon-specs">{weapon ? <div className="wardogs-weapon-panels">
    <section className="wardogs-weapon-panel"><h2>武器數值</h2>
    <dl className="wardogs-detail-stats">
      <div><dt>射速</dt><dd>{weapon.rpm === undefined ? '未提供' : `${weapon.rpm} 發／分鐘`}</dd></div>
      <div><dt>射擊模式</dt><dd>{weapon.fireModes?.map(mode => modes[mode] || mode).join('、') || '未提供'}</dd></div>
      <div><dt>口徑</dt><dd>{weapon.calibers?.join('、') || '未提供'}</dd></div>
      <div><dt>槍口初速</dt><dd>{weapon.muzzleVelocity === undefined ? '未提供' : `${weapon.muzzleVelocity} m/s`}</dd></div>
      <div><dt>有效射程</dt><dd>{weapon.effectiveRange === undefined ? '未提供' : `${weapon.effectiveRange} m`}</dd></div>
      <div><dt>精準度MOA</dt><dd>{weapon.accuracy ?? '未提供'}</dd></div>
      <div><dt>單發傷害</dt><dd>{weapon.meleeDamage ?? '未提供'}</dd></div>
    </dl>
    </section>
    <section className="wardogs-weapon-panel"><h2>傷害衰減</h2><FalloffChart points={weapon.damageFalloff ?? []} /></section>
    <section className="wardogs-weapon-panel wardogs-recoil-panel"><RecoilChart pattern={weapon.recoil?.pattern ?? []} resetTime={weapon.recoil?.patternResetTime} /></section>
    <section className="wardogs-weapon-panel"><h2>操控與後座力</h2>
      <dl className="wardogs-detail-stats">
        <div><dt>隨機偏移</dt><dd>{weapon.randomDeviation ?? '未提供'}</dd></div>
        <div><dt>鏡頭後座倍率</dt><dd>{weapon.recoil?.viewKickMultiplier ?? '未提供'}</dd></div>
        <div><dt>模式結束後垂直偏移</dt><dd>{weapon.recoil?.afterPatternPitch?.join(' ～ ') || '未提供'}</dd></div>
        <div><dt>模式結束後水平偏移</dt><dd>{weapon.recoil?.afterPatternYaw?.join(' ～ ') || '未提供'}</dd></div>
      </dl>
      <p>以上為來源原始操控數值，未套用角色技能或配件效果。</p>
    </section>
  </div> : <p>來源未提供這件武器的數值。</p>}</section>
}

function RecoilChart({ pattern, resetTime }: { pattern: RecoilPoint[]; resetTime?: number }) {
  const titleId = useId()
  const descriptionId = useId()
  const [shots, setShots] = useState(pattern.length)
  const points = recoilPath(pattern)
  if (points.length < 2) return <section><h2>後座力模擬</h2><p>來源未提供可繪製的後座力模式。</p></section>
  const xValues = points.map(point => point.x)
  const yValues = points.map(point => point.y)
  const minX = Math.min(...xValues), maxX = Math.max(...xValues)
  const minY = Math.min(...yValues), maxY = Math.max(...yValues)
  const scale = Math.min(360 / Math.max(maxX - minX, 1), 300 / Math.max(maxY - minY, 1))
  const x = (value: number) => 240 + (value - (minX + maxX) / 2) * scale
  const y = (value: number) => 350 - (value - minY) * scale
  const visible = points.slice(0, shots + 1)
  return <section className="wardogs-recoil"><h2>後座力模擬</h2>
    <label>連射發數：{shots} / {pattern.length}<input type="range" min="1" max={pattern.length} value={shots} onChange={event => setShots(Number(event.target.value))} /></label>
    <svg viewBox="0 0 480 400" role="img" aria-labelledby={`${titleId} ${descriptionId}`}>
      <title id={titleId}>連續射擊 {shots} 發的累積後座力軌跡</title>
      <desc id={descriptionId}>從起點開始，依序累加每發水平與垂直後座力；紅點表示最後一發的位置。</desc>
      <line x1={x(0)} x2={x(0)} y1="24" y2="365" stroke="#ccd7d7" strokeDasharray="5 5" />
      <line x1="35" x2="445" y1={y(0)} y2={y(0)} stroke="#ccd7d7" strokeDasharray="5 5" />
      <polyline points={visible.map(point => `${x(point.x)},${y(point.y)}`).join(' ')} fill="none" stroke="#176a61" strokeWidth="2" />
      {visible.map((point, index) => <circle key={index} cx={x(point.x)} cy={y(point.y)} r={index === shots ? 5 : 3} fill={index === shots ? '#b94b3d' : '#176a61'}><title>{index === 0 ? '起點' : `第 ${index} 發`}：水平 {point.x.toFixed(3)}，垂直 {point.y.toFixed(3)}</title></circle>)}
      <text x="16" y="20" fill="#52646a" fontSize="13">↑ 垂直後座力</text><text x="340" y="390" fill="#52646a" fontSize="13">水平後座力 →</text>
      <text x={x(0) + 8} y={y(0) + 18} fill="#52646a" fontSize="12">起點</text>
    </svg>
    <p>依每發原始後座力累加，水平與垂直採相同比例。來源未標示單位；圖形未套用壓槍、配件、隨機偏移或射擊間回復，並非實際彈著點。</p>
    {resetTime !== undefined && <p>模式重置時間：停止射擊 {resetTime} 秒。</p>}
  </section>
}


function FalloffChart({ points }: { points: { distance: number; multiplier: number }[] }) {
  const titleId = useId()
  const sorted = points.filter(point => Number.isFinite(point.distance) && Number.isFinite(point.multiplier)).sort((a, b) => a.distance - b.distance)
  if (!sorted.length) return <p>來源未提供傷害衰減資料。</p>
  const maxDistance = Math.max(1, ...sorted.map(point => point.distance))
  const maxMultiplier = Math.max(1, ...sorted.map(point => point.multiplier))
  const x = (distance: number) => 48 + distance / maxDistance * 380
  const y = (multiplier: number) => 190 - multiplier / maxMultiplier * 160
  return <div className="wardogs-falloff">
    <svg viewBox="0 0 460 240" role="img" aria-labelledby={titleId}>
      <title id={titleId}>傷害倍率隨距離變化</title>
      {[0, .5, 1].map(fraction => <g key={fraction}><line x1="48" x2="428" y1={y(fraction * maxMultiplier)} y2={y(fraction * maxMultiplier)} stroke="#d7dfdf" strokeDasharray="4 4" /><text x="4" y={y(fraction * maxMultiplier) + 4} fill="#52646a" fontSize="12">{Math.round(fraction * maxMultiplier * 100)}%</text></g>)}
      <polyline points={sorted.map(point => `${x(point.distance)},${y(point.multiplier)}`).join(' ')} fill="none" stroke="#176a61" strokeWidth="3" />
      {sorted.map((point, index) => <circle key={index} cx={x(point.distance)} cy={y(point.multiplier)} r="4" fill="#176a61"><title>{point.distance} m：{(point.multiplier * 100).toFixed(1)}%</title></circle>)}
      <text x="48" y="220" fill="#52646a" fontSize="12">0 m</text><text x="428" y="220" textAnchor="end" fill="#52646a" fontSize="12">{maxDistance} m</text>
    </svg>
    <dl className="wardogs-detail-stats">{sorted.map((point, index) => <div key={index}><dt>{point.distance} m</dt><dd>{Number((point.multiplier * 100).toFixed(1))}%</dd></div>)}</dl>
    <p>顯示武器的傷害倍率，非套用彈種與護甲後的實際傷害。</p>
  </div>
}
