import { ArrowUpRight } from 'lucide-react'
import teamLogo from './assets/SIT隊徽(去背).png'
import './App.css'
import Administrators from './components/Administrators'
import Account from './components/Account'
import Profile from './pages/Profile'
import { Link, Route, Routes } from 'react-router-dom'

const discordUrl = 'https://discord.com/invite/VmeJwTv'

function App() {
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
            <h1 id="hero-title">網頁開發中</h1>
            <p className="hero-description">SIT — Star Impact Team。<br /> </p>
            <a className="primary-link" href={discordUrl} target="_blank" rel="noopener noreferrer">加入 Discord <ArrowUpRight size={20} aria-hidden="true" /></a>
          </div>

          <div className="hero-art" role="img" aria-label="SIT 隊徽，搭配橘金色星光與軌道">
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
    </>
  )
}
export default App
