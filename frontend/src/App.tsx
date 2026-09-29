/** Application shell, community homepage, and account/profile routes. */
import { ArrowUpRight } from 'lucide-react'
import { useState } from 'react'
import teamLogo from './assets/SIT隊徽(去背).png'
import './App.css'
import Administrators from './components/Administrators'
import Account from './components/Account'
import Profile from './pages/Profile'
import InvitationDialog from './components/InvitationDialog'
import { Link, Route, Routes } from 'react-router-dom'

/** Render the shared navigation and footer around the active client-side route. */
function App() {
  const [invitationOpen, setInvitationOpen] = useState(false)
  return (
    <>
      <a className="skip-link" href="#main-content">跳至主要內容</a>
      <header className="topbar">
        <Link to="/" className="brand" aria-label="SIT Star Impact Team 首頁">
          <img src={teamLogo} alt="" />
          <span>SIT<span className="brand-subtitle">STAR IMPACT TEAM</span></span>
        </Link>
        <nav aria-label="帳號"><Account /></nav>
      </header>

      <main id="main-content">
        <Routes>
          <Route path="/" element={<>
        <section className="hero" aria-labelledby="hero-title">
          <div className="hero-copy">
            <h1 id="hero-title">Star Impact Team</h1>
            <p className="hero-description">
                Star Impact Team（簡稱 SIT）是一個私人社群。
                <br />
                本網站提供社群成員參與活動、互動交流及各項娛樂功能。
                <br />
                您需要加入 Discord 群組並且擁有「成員」或以上身分組，才能使用本網站大部分功能。
            </p>
            <button type="button" className="primary-link invitation-trigger" onClick={() => setInvitationOpen(true)} aria-haspopup="dialog">加入 Discord <ArrowUpRight size={20} aria-hidden="true" /></button>
          </div>

          <div className="hero-art" role="img" aria-label="SIT">
            <div className="orbit orbit-one" />
            <div className="orbit orbit-two" />
            <span className="star star-one">✦</span><span className="star star-two">✧</span><span className="star star-three">✦</span>
            <img className="hero-logo" src={teamLogo} alt="" fetchPriority="high" />
            <div className="art-caption"><span>STAR IMPACT TEAM</span></div>
          </div>
        </section>

        <Administrators />

          </>} />
          <Route path="/profile" element={<Profile />} />
          <Route path="*" element={<section className="profile-page"><h1>找不到此頁面</h1><Link to="/">返回首頁</Link></section>} />
        </Routes>

      </main>
      <footer><Link to="/" className="footer-brand">SIT <span>STAR IMPACT TEAM</span></Link><span>© {new Date().getFullYear()} SIT</span></footer>
      {invitationOpen && <InvitationDialog onClose={() => setInvitationOpen(false)} />}
    </>
  )
}
export default App
