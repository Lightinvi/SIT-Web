import { ArrowDown, ArrowUpRight, Sparkles } from 'lucide-react'
import teamLogo from './assets/SIT隊徽(去背).png'
import './App.css'

const discordUrl = 'https://discord.com/invite/VmeJwTv'

function App() {
  return (
    <>
      <a className="skip-link" href="#about">跳至團隊介紹</a>
      <header className="topbar">
        <a href="/" className="brand" aria-label="SIT Star Impact Team 首頁">
          <img src={teamLogo} alt="" />
          <span>SIT<span className="brand-subtitle">STAR IMPACT TEAM</span></span>
        </a>
        <nav aria-label="主要導覽">
          <a className="about-link" href="#about">關於我們</a>
          <a className="nav-discord" href={discordUrl} target="_blank" rel="noopener noreferrer">加入 Discord <ArrowUpRight size={16} aria-hidden="true" /></a>
        </nav>
      </header>

      <main>
        <section className="hero" aria-labelledby="hero-title">
          <div className="hero-copy">
            <p className="eyebrow"><span /> THIS IS OUR ORBIT</p>
            <h1 id="hero-title">網頁開發中</h1>
            <p className="hero-description">SIT — Star Impact Team。<br />在這裡，一起遊玩一起歡樂</p>
            <a className="primary-link" href={discordUrl} target="_blank" rel="noopener noreferrer">加入我們的 Discord <ArrowUpRight size={20} aria-hidden="true" /></a>
            <a className="explore-link" href="#about"><ArrowDown size={15} aria-hidden="true" /> 認識 SIT <span>往下探索</span></a>
          </div>

          <div className="hero-art" role="img" aria-label="SIT 隊徽，搭配橘金色星光與軌道">
            <div className="art-label"><span className="tiny-star">✦</span> A SHARED PASSION. A SHARED UNIVERSE.</div>
            <div className="orbit orbit-one" />
            <div className="orbit orbit-two" />
            <span className="star star-one">✦</span><span className="star star-two">✧</span><span className="star star-three">✦</span>
            <img className="hero-logo" src={teamLogo} alt="" fetchPriority="high" />
            <div className="art-caption"><span>STAR IMPACT TEAM</span><span>一起，閃耀。</span></div>
          </div>
        </section>

        <section className="about-section" id="about" aria-labelledby="about-title">
          <div className="section-label"><span>01 / ABOUT US</span><Sparkles size={20} aria-hidden="true" /></div>
          <div className="about-content">
            <p className="eyebrow">HELLO, WE ARE SIT</p>
            <h2 id="about-title">一群夥伴，一份共同的熱愛。</h2>
            <p>Star Impact Team，簡稱 SIT。我們相信，每一份熱情都有自己的光芒；當志同道合的夥伴聚在一起，就能碰撞出更多可能。</p>
            <p>無論是交流日常、分享喜愛的事物，或一起迎接新的挑戰，這裡都歡迎你的加入。讓我們從一聲招呼開始，寫下下一段共同的故事。</p>
            <div className="team-signature"><span>✦</span> CONNECT. SHARE. SHINE.</div>
          </div>
        </section>

        <section className="community" aria-labelledby="community-title">
          <div className="community-symbol" aria-hidden="true">✳</div>
          <div className="community-copy"><p className="eyebrow">YOUR NEXT CONNECTION STARTS HERE</p><h2 id="community-title">下一位夥伴，就是你。</h2><p>來 Discord 打聲招呼，加入我們的日常。</p></div>
          <a className="community-link" href={discordUrl} target="_blank" rel="noopener noreferrer">前往 Discord <ArrowUpRight size={20} aria-hidden="true" /></a>
        </section>
      </main>
      <footer><a href="/" className="footer-brand">SIT <span>STAR IMPACT TEAM</span></a><span>因熱愛而相聚，因彼此而閃耀。</span><span>© {new Date().getFullYear()} SIT</span></footer>
    </>
  )
}
export default App
