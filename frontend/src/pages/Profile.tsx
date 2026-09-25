import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'

import Avatar from '../components/Avatar'

type Member = { user_id: string; username: string | null; display_name: string | null; global_name: string | null; nickname: string | null; avatar_url: string | null; guild_joined_at: string | null; created_at: number; last_login_at: number }

export default function Profile() {
  const [member, setMember] = useState<Member | null>(null)
  const [status, setStatus] = useState<'loading' | 'ready' | 'anonymous' | 'missing' | 'error'>('loading')
  const [attempt, setAttempt] = useState(0)
  const heading = useRef<HTMLHeadingElement>(null)

  useEffect(() => {
    heading.current?.focus({ preventScroll: true })
    window.scrollTo(0, 0)
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    let disposed = false
    const timeout = window.setTimeout(() => controller.abort(), 10000)
    fetch('/api/auth/profile', { signal: controller.signal, cache: 'no-store' })
      .then(async response => {
        if (disposed) return
        if (response.status === 401) { setStatus('anonymous'); return }
        if (response.status === 404) { setStatus('missing'); return }
        if (!response.ok) throw new Error()
        const data = await response.json()
        if (disposed) return
        if (!data.member || typeof data.member.user_id !== 'string') throw new Error()
        setMember(data.member)
        setStatus('ready')
      }).catch(() => { if (!disposed) setStatus('error') })
      .finally(() => window.clearTimeout(timeout))
    return () => { disposed = true; controller.abort(); window.clearTimeout(timeout) }
  }, [attempt])

  const formatDate = (value: number) => new Date(value * 1000).toLocaleString('zh-TW', { hour12: false })

  return <section className="profile-page" aria-labelledby="profile-title">
    <Link to="/" className="profile-back"><ArrowLeft size={16} aria-hidden="true" />返回首頁</Link>
    <p className="eyebrow">SIT ACCOUNT</p>
    <h1 id="profile-title" ref={heading} tabIndex={-1}>個人資料</h1>
    <p className="profile-intro"></p>
    {status === 'loading' && <p className="profile-notice" role="status">正在載入個人資料…</p>}
    {status === 'anonymous' && <div className="profile-notice"><p>請先登入帳號，查看你的個人資料。</p><a className="primary-link" href="/api/auth/discord/login">使用 Discord 登入</a></div>}
    {status === 'missing' && <p className="profile-notice" role="status">尚無個人資料，請從右上角登出後重新登入。</p>}
    {status === 'error' && <div className="profile-notice" role="alert"><p>暫時無法載入個人資料。</p><button className="account-button" onClick={() => { setStatus('loading'); setAttempt(value => value + 1) }}>重新載入</button></div>}
    {status === 'ready' && member && <div className="profile-card">
      <div className="profile-identity"><Avatar src={member.avatar_url} name={member.display_name || member.username || '使用者'} className="profile-avatar" /><div><h2>{member.display_name || member.username || 'SIT 成員'}</h2><p>Discord 帳號</p></div></div>
      <dl className="profile-fields">
        <div><dt>Discord 使用者 ID</dt><dd>{member.user_id}</dd></div>
        <div><dt>帳號名稱</dt><dd>{member.username || '未提供'}</dd></div>
        <div><dt>顯示名稱</dt><dd>{member.display_name || '未提供'}</dd></div>
        <div><dt>Discord 顯示名稱</dt><dd>{member.global_name || '未設定'}</dd></div>
        <div><dt>社群暱稱</dt><dd>{member.nickname || '未設定'}</dd></div>
        <div><dt>加入社群時間</dt><dd>{member.guild_joined_at ? new Date(member.guild_joined_at).toLocaleString('zh-TW', { hour12: false }) : '尚無紀錄'}</dd></div>
        <div><dt>首次登入</dt><dd>{formatDate(member.created_at)}</dd></div>
        <div><dt>最近登入</dt><dd>{formatDate(member.last_login_at)}</dd></div>
      </dl>
      <p className="profile-footnote">資料於每次 Discord 登入時更新；若資料不正確請嘗試重新登入以同步新增資料。</p>
    </div>}
  </section>
}
