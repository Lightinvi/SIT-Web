/** Signed-in feature navigation with reserved grid tracks and an expandable introduction. */
import type { ReactNode } from 'react'
import { ArrowLeft, ArrowUpRight, CircleHelp, Disc3 } from 'lucide-react'
import { Link, useSearchParams } from 'react-router-dom'
import type { LoginSession } from '../components/Account'
import teamLogo from '../assets/SIT隊徽(去背).png'
import shardIcon from '../assets/star_shard.png'
import './Home.css'

/** Keep the original introduction on the homepage without rendering empty feature cards. */
export default function Home({ account, children }: { account: LoginSession | null; children: ReactNode }) {
  const [params, setParams] = useSearchParams()
  if (account === null) return <section className="home-loading" role="status">載入中…</section>
  if (!account.authenticated || params.get('view') === 'introduction') return <>
    {account.authenticated && <button className="home-return" onClick={() => { setParams({}); window.scrollTo(0, 0) }}><ArrowLeft size={17} />返回功能選項</button>}
    {children}
  </>
  return <section className="home-functions" aria-labelledby="home-functions-title">
    <h1 id="home-functions-title">功能導覽</h1>
    <div className="home-function-grid">
      <button className="home-feature" onClick={() => { setParams({ view: 'introduction' }); window.scrollTo(0, 0) }}>
        <img src={teamLogo} alt="" /><span><CircleHelp size={18} />介紹</span><ArrowUpRight className="home-feature-arrow" size={18} />
      </button>
      <Link className="home-feature" to="/daily-spinner">
        <img src={shardIcon} alt="" /><span><Disc3 size={18} />每日轉盤</span><ArrowUpRight className="home-feature-arrow" size={18} />
      </Link>
    </div>
  </section>
}
