import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, ArrowRight, Pause, Play, ShieldCheck } from 'lucide-react'
import { getAdministrators } from '../api/discord'
import type { Administrator } from '../api/discord'
import teamLogo from '../assets/SIT隊徽(去背).png'

export default function Administrators() {
  const [members, setMembers] = useState<Administrator[]>([])
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  const [attempt, setAttempt] = useState(0)
  const [index, setIndex] = useState(0)
  const [paused, setPaused] = useState(false)
  const [hovered, setHovered] = useState(false)
  const [focused, setFocused] = useState(false)
  const [reducedMotion, setReducedMotion] = useState(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches)
  const [resetting, setResetting] = useState(false)
  const touchStart = useRef<number | null>(null)

  useEffect(() => {
    const preference = window.matchMedia('(prefers-reduced-motion: reduce)')
    const update = () => setReducedMotion(preference.matches)
    preference.addEventListener('change', update)
    return () => preference.removeEventListener('change', update)
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    let disposed = false
    const timeout = window.setTimeout(() => controller.abort(), 25000)
    getAdministrators(controller.signal).then(data => {
      if (disposed) return
      setMembers(data)
      setIndex(0)
      setStatus('ready')
    }).catch(() => {
      if (!disposed) setStatus('error')
    }).finally(() => window.clearTimeout(timeout))
    return () => { disposed = true; controller.abort(); window.clearTimeout(timeout) }
  }, [attempt])

  useEffect(() => {
    if (paused || hovered || focused || reducedMotion || members.length < 2) return
    const timer = window.setInterval(() => {
      if (document.hidden) return
      setIndex(current => Math.min(current + 1, members.length))
    }, 5000)
    return () => window.clearInterval(timer)
  }, [paused, hovered, focused, reducedMotion, members.length])

  // The extra first slide lets the final transition keep moving right.
  // Reset to the identical original without animating back across the track.
  useEffect(() => {
    if (members.length < 2 || index !== members.length) return
    const timer = window.setTimeout(() => {
      setResetting(true)
      setIndex(0)
    }, reducedMotion ? 0 : 650)
    return () => window.clearTimeout(timer)
  }, [index, members.length, reducedMotion])

  useEffect(() => {
    if (!resetting) return
    let secondFrame = 0
    const firstFrame = window.requestAnimationFrame(() => {
      secondFrame = window.requestAnimationFrame(() => setResetting(false))
    })
    return () => {
      window.cancelAnimationFrame(firstFrame)
      window.cancelAnimationFrame(secondFrame)
    }
  }, [resetting])

  function move(step: number) {
    setPaused(true)
    if (resetting || index === members.length) return
    setIndex(current => Math.max(0, Math.min(members.length, current + step)))
  }

  const slides = members.length > 1 ? [...members, members[0]] : members
  const activeIndex = members.length ? index % members.length : 0

  return (
    <section className="admins-section" id="administrators" aria-labelledby="admins-title">
      <div className="admins-heading">
        <div><h2 id="admins-title">社群管理員</h2><p className="admins-intro"></p></div>
        <span className="admins-label"><ShieldCheck size={17} aria-hidden="true" /> SIT DISCORD TEAM</span>
      </div>
      {status === 'loading' && <div className="admins-message" role="status">正在尋找星空中的夥伴…</div>}
      {status === 'error' && <div className="admins-message" role="alert"><p>暫時無法載入管理員，請稍後再試。</p><button onClick={() => { setStatus('loading'); setAttempt(value => value + 1) }}>重新載入</button></div>}
      {status === 'ready' && members.length === 0 && <p className="admins-message">目前尚無可顯示的管理員。</p>}
      {status === 'ready' && members.length > 0 && (
        <div className="admin-carousel" role="region" aria-roledescription="輪播" aria-label="Discord 社群管理員"
          onMouseEnter={() => setHovered(true)} onMouseLeave={() => setHovered(false)}
          onFocusCapture={() => setFocused(true)} onBlurCapture={event => { if (!event.currentTarget.contains(event.relatedTarget)) setFocused(false) }}
          onKeyDown={event => {
            if (event.key === 'ArrowLeft') { event.preventDefault(); move(-1) }
            if (event.key === 'ArrowRight') { event.preventDefault(); move(1) }
          }}>
          <div className="admin-viewport" onTouchStart={event => { touchStart.current = event.touches[0].clientX }}
            onTouchCancel={() => { touchStart.current = null }} onTouchEnd={event => {
              if (touchStart.current !== null) {
                const distance = event.changedTouches[0].clientX - touchStart.current
                if (Math.abs(distance) > 45) move(distance > 0 ? 1 : -1)
              }
              touchStart.current = null
            }}>
            <div className="admin-track" style={{ transform: `translateX(${index * 100}%)`, transition: resetting ? 'none' : undefined }}>
              {slides.map((member, position) => (
                <article className="admin-slide" key={`${member.id}-${position}`} aria-hidden={position !== index} aria-roledescription="投影片" aria-label={`${position % members.length + 1} / ${members.length}`}>
                  <div className="admin-portrait"><span aria-hidden="true" className="portrait-star">✦</span><img src={member.avatar} alt={`${member.name} 的頭像`} loading="lazy" onError={event => { event.currentTarget.onerror = null; if (event.currentTarget.src !== teamLogo && !event.currentTarget.src.endsWith(teamLogo)) event.currentTarget.src = teamLogo }} /></div>
                  <div className="admin-details"><p className="eyebrow">COMMUNITY ADMINISTRATOR</p><h3>{member.name}</h3><p className="admin-username">@{member.username}</p><span className="admin-role"><ShieldCheck size={14} aria-hidden="true" />{member.role}</span></div>
                </article>
              ))}
            </div>
          </div>
          <div className="admin-controls">
            <span className="admin-count" aria-live={paused || focused || reducedMotion ? 'polite' : 'off'}>{String(activeIndex + 1).padStart(2, '0')} <span>/ {String(members.length).padStart(2, '0')}</span></span>
            {members.length > 1 && <div className="admin-buttons">
              {!reducedMotion && <button aria-label={paused ? '播放管理員輪播' : '暫停管理員輪播'} onClick={() => setPaused(value => !value)}>{paused ? <Play size={16} /> : <Pause size={16} />}</button>}
              <button aria-label="上一位管理員" disabled={index === 0} onClick={() => move(-1)}><ArrowLeft size={19} /></button>
              <button aria-label="下一位管理員" disabled={resetting || index === members.length} onClick={() => move(1)}><ArrowRight size={19} /></button>
            </div>}
          </div>
        </div>
      )}
    </section>
  )
}
