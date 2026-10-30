/** Search public Wardogs item data without requiring the site's administrator APIs. */
import { useEffect, useState } from 'react'
import { ArrowLeft, Database, Package, ArrowRight } from 'lucide-react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { wardogsRoleName } from '../utils/wardogsRoles'
import { WARDOGS_CATEGORIES, wardogsCategory } from '../utils/wardogsCategories'
import WardogsDamageSimulator from '../components/WardogsDamageSimulator'
import type { DamageModel } from '../utils/wardogsDamage'
import WardogsWeaponDetails from '../components/WardogsWeaponDetails'
import './Home.css'
import './WardogsDatabase.css'

type Item = { id: string; asset?: string; tags?: string[]; icon?: string; name?: string; subtitle?: string; kind?: string; description?: string; weight?: number; maxStack?: number; grid?: number[]; durability?: number; unlock?: { role?: string; level?: number; cost?: number } | null; vendor?: { tag: string; price?: number; amount?: number; categories?: string[] }[] }
type ItemData = { gameBuild: string; release: string; stale?: boolean; checkedAt: number; items: Item[] }
const source = 'https://github.com/warpuppies/wardogs-data'

export default function WardogsDatabase() {
  const { itemId } = useParams<{ itemId: string }>()
  const [data, setData] = useState<ItemData | null>(null)
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  const [search, setSearch] = useState('')
  const [params, setParams] = useSearchParams()
  const requestedCategory = params.get('category') || ''
  const kind = WARDOGS_CATEGORIES.find(category => category === requestedCategory) || ''
  const [page, setPage] = useState(0)
  useEffect(() => {
    let active = true
    const controller = new AbortController()
    const timeout = window.setTimeout(() => controller.abort(), 600000)
    async function load() {
      try {
        const response = await fetch('/api/wardogs/items', { signal: controller.signal })
        if (!response.ok) {
          const failure = await response.json()
          throw new Error(failure.error || '無法載入 WARDOGS 資料，請稍後重試。')
        }
        const result = await response.json()
        if (!result || !Array.isArray(result.items) || typeof result.gameBuild !== 'string' ||
            !result.items.every((item: Item) => item && typeof item.id === 'string' &&
              ['name', 'subtitle', 'kind', 'description'].every(key => item[key as keyof Item] === undefined || typeof item[key as keyof Item] === 'string'))) {
          throw new Error('資料來源格式不符，請稍後重試。')
        }
        if (!controller.signal.aborted) setData(result)
      } catch (cause) {
        if (active) setError(controller.signal.aborted ? '資料載入逾時，請重試。' : cause instanceof Error ? cause.message : '無法載入資料。')
      } finally { window.clearTimeout(timeout) }
    }
    void load()
    return () => { active = false; controller.abort(); window.clearTimeout(timeout) }
  }, [attempt])
  const query = search.trim().toLocaleLowerCase()
  const items = (data?.items ?? []).filter(item => (!kind || wardogsCategory(item) === kind) &&
    `${item.name ?? ''} ${item.id} ${item.description ?? ''}`.toLocaleLowerCase().includes(query))
  const kinds = WARDOGS_CATEGORIES
  const selectedItem = data?.items.find(item => item.id === itemId)
  if (itemId && data && !error) return selectedItem
    ? <ItemDetails key={selectedItem.id} item={selectedItem} data={data} />
    : <section className="wardogs-database"><Link className="home-return" to="/wardogs/database"><ArrowLeft size={17} />返回資料庫</Link><h1>找不到此物品</h1><p>這件物品可能已在資料更新後移除。</p></section>
  return <section className="wardogs-database" aria-labelledby="wardogs-database-title">
    <Link className="home-return" to="/wardogs"><ArrowLeft size={17} />返回 WARDOGS</Link>
    <h1 id="wardogs-database-title"><Database size={28} aria-hidden="true" />WARDOGS 資料庫</h1>
    <p>物品資料來源：<a href={source} target="_blank" rel="noreferrer">warpuppies / wardogs-data</a>{data && ` · 遊戲版本 ${data.gameBuild}`}</p>
    <p>非官方資料，遊戲內數值可能隨版本及伺服器設定變動。</p>
    {error ? <div role="alert"><p>{error}</p><button onClick={() => { setError(''); setData(null); setAttempt(value => value + 1) }}>重新載入</button></div> : !data ? <p role="status">正在載入物品資料…</p> : <>
      {data.stale && <p role="status">暫時無法更新，正在使用本地快取資料。</p>}
      <p>最後檢查：{new Date(data.checkedAt * 1000).toLocaleString()}</p>
      {!kind ? <div className="wardogs-category-grid">{kinds.map(value => {
        const members = data.items.filter(item => wardogsCategory(item) === value)
        const representative = members.find(item => item.icon)
        return <button className="wardogs-category" key={value} onClick={() => { setParams({ category: value }); setSearch(''); setPage(0) }}>
          {representative?.icon ? <ItemImage item={representative} release={data.release} /> : <Package size={48} aria-hidden="true" />}
          <strong>{value}</strong><span>{members.length} 件物品</span><ArrowRight size={18} aria-hidden="true" />
        </button>
      })}</div> : <>
      <button className="home-return" onClick={() => { setParams({}); setPage(0); setSearch('') }}><ArrowLeft size={17} />返回分類</button>
      <h2>{kind}</h2>
      <div className="wardogs-filters"><label>搜尋物品<input type="search" value={search} placeholder="名稱、ID 或描述" onChange={event => { setSearch(event.target.value); setPage(0) }} /></label></div>
      <p role="status">共 {items.length} 件物品</p>
      <div className="wardogs-item-grid">{items.slice(page * 50, (page + 1) * 50).map((item, index) => <Link className="wardogs-item" to={`/wardogs/database/items/${encodeURIComponent(item.id)}`} key={`${item.id}-${index}`}>
        <ItemImage item={item} release={data.release} /><h3>{item.name || item.id}</h3>
      </Link>)}</div>
      {!items.length && <p>找不到符合條件的物品。</p>}
      <nav className="wardogs-pagination" aria-label="物品資料分頁"><button disabled={page === 0} onClick={() => setPage(value => value - 1)}>上一頁</button><span>{page + 1} / {Math.max(1, Math.ceil(items.length / 50))}</span><button disabled={(page + 1) * 50 >= items.length} onClick={() => setPage(value => value + 1)}>下一頁</button></nav>
      </>}
    </>}
  </section>
}

function ItemImage({ item, release }: { item: Item; release: string }) {
  const [failed, setFailed] = useState(false)
  return item.icon && !failed ? <img loading="lazy" src={`/api/wardogs/icons/${encodeURIComponent(release)}/${item.icon.split('/').map(encodeURIComponent).join('/')}`} alt="" onError={() => setFailed(true)} /> : <div className="wardogs-no-image"><Package size={42} aria-hidden="true" /><span>暫無圖片</span></div>
}


type SourceSection = { source: string; collection: string; title: string; records: Record<string, unknown>[] }
function ItemDetails({ item: baseItem, data }: { item: Item; data: ItemData }) {
  const [detail, setDetail] = useState<{ item: Item; sections: SourceSection[]; checkedSources: string[]; priceSource?: { source: string; label: string; publishedAt: string } | null; simulation?: DamageModel | null; ammoDetails?: { damage: number | null; weapons: { id: string; name: string }[] } | null } | null>(null)
  const [detailError, setDetailError] = useState('')
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    fetch(`/api/wardogs/items/${encodeURIComponent(baseItem.id)}`, { signal: controller.signal, cache: 'no-store' })
      .then(async response => {
        const result = await response.json()
        if (!response.ok) throw new Error(result.error || '無法載入補充資料。')
        if (result.release !== data.release) throw new Error('資料版本已更新，請重新整理頁面。')
        setDetail(result)
      }).catch(error => { if (!controller.signal.aborted) setDetailError(error.message) })
    return () => controller.abort()
  }, [baseItem.id, data.release, attempt])
  const item = detail?.item ?? baseItem
  const category = wardogsCategory(item)
  return <section className={`wardogs-database wardogs-detail${category === '武器' ? ' wardogs-weapon-page' : ''}`} aria-labelledby="wardogs-item-title">
    <Link className="home-return" to={`/wardogs/database?category=${encodeURIComponent(category)}`}><ArrowLeft size={17} />返回{category}</Link>
    <div className="wardogs-detail-layout">
    <aside className="wardogs-item-sidebar">
    <div className="wardogs-detail-heading">
      <div className="wardogs-detail-image"><ItemImage item={item} release={data.release} /></div>
      <div><p className="wardogs-detail-category">{category}</p><h1 id="wardogs-item-title">{item.name || item.id}</h1><p className="wardogs-detail-id">{item.id}</p>
        {category !== '武器' && (item.description ? <p className="wardogs-detail-description">{item.description}</p> : <p>來源未提供物品描述。</p>)}
      </div>
    </div>
    {detailError && <div role="alert"><p>{detailError}</p><button onClick={() => { setDetailError(''); setAttempt(value => value + 1) }}>重試補充資料</button></div>}
    {!detail && !detailError && <p role="status">正在驗證其他資料來源…</p>}
    <h2>基本資料</h2>
    <dl className="wardogs-detail-stats">
      <div><dt>分類</dt><dd>{category}</dd></div>
      <div><dt>商店售價</dt><dd>{[...new Set((item.vendor ?? []).flatMap(vendor => typeof vendor.price === 'number' ? [vendor.price] : []))].map(price => price.toLocaleString()).join(' / ') || '未提供'}{detail?.priceSource && <small><a href={detail.priceSource.source} target="_blank" rel="noreferrer">{detail.priceSource.label}</a></small>}</dd></div>
      {category === '彈藥' && <div><dt>每發基礎傷害</dt><dd>{!detail ? '載入中…' : detail.ammoDetails?.damage ?? '未提供'}</dd></div>}
      <div><dt>重量</dt><dd>{item.weight ?? '未提供'}</dd></div>
      <div><dt>堆疊上限</dt><dd>{item.maxStack ?? '未提供'}</dd></div>
      <div><dt>背包佔用格數</dt><dd>{item.grid?.length === 2 ? `${item.grid[0]} × ${item.grid[1]}` : '未提供'}</dd></div>
    </dl>
    <h2>解鎖條件</h2>
    {item.unlock ? <dl className="wardogs-detail-stats">
      <div><dt>職業</dt><dd>{wardogsRoleName(item.unlock.role)}</dd></div>
      <div><dt>等級</dt><dd>{item.unlock.level ?? '未提供'}</dd></div>
      <div><dt>費用</dt><dd>{item.unlock.cost?.toLocaleString() ?? '未提供'}</dd></div>
    </dl> : <p>來源未提供解鎖條件。</p>}
    </aside>
    <div className="wardogs-item-main">
    {category === '武器' && <section className="wardogs-weapon-intro"><h2>武器概覽</h2><p className="wardogs-detail-description">{item.description || '來源未提供物品描述。'}</p></section>}
    {detail && category === '武器' && <WardogsWeaponDetails weapon={detail.sections.find(section => section.source === 'weapons.json' && section.collection === 'weapons')?.records.find(record => typeof record.id === 'string' && record.id.toLowerCase() === item.id.toLowerCase())} />}
    {category === '彈藥' && <section className="wardogs-ammo-weapons"><h2>適用武器</h2>
      {!detail ? <p role="status">正在核對適用武器…</p> : detail.ammoDetails?.weapons.length ? <div className="wardogs-ammo-links">{detail.ammoDetails.weapons.map(weapon => <Link key={weapon.id} to={`/wardogs/database/items/${encodeURIComponent(weapon.id)}`}><strong>{weapon.name}</strong><span>查看武器詳細資料 →</span></Link>)}</div> : <p>來源未提供可確認的適用武器。</p>}
    </section>}
    {category === '武器' && detail?.simulation && <WardogsDamageSimulator model={detail.simulation} />}
    </div>
    </div>
    <p>遊戲版本 {data.gameBuild} · <a href={source} target="_blank" rel="noreferrer">資料來源：warpuppies / wardogs-data</a></p>
    <p>非官方資料，遊戲內數值可能隨版本及伺服器設定變動。</p>
  </section>
}

