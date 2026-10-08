/** Read-only database and application log inspection for web administrators. */
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import Select from 'react-select'
import { ArrowLeft, ArrowDown, ArrowUp, ChevronsUpDown, RefreshCw, Search } from 'lucide-react'
import './AdminViewer.css'

type Row = Record<string, unknown>
const logFields: Record<string, string> = { timestamp: '時間', level: '等級', requestId: '請求 ID', message: '訊息', route: '路由', method: '方法', status: '狀態', durationMs: '請求耗時 (ms)' }

/** Render values as plain text, preserving nulls and formatting log times locally. */
function cell(value: unknown, column: string, logs: boolean) {
  if (value === null || value === undefined) return '—'
  if (logs && column === 'timestamp' && typeof value === 'string') {
    const date = new Date(value)
    if (!Number.isNaN(date.getTime())) return date.toLocaleString(undefined, { hour12: false })
  }
  return typeof value === 'object' ? JSON.stringify(value) : String(value)
}

/** Fetch sequential pages; restarting the component discards obsolete requests and rows. */
function Records({ table, logs, sort, direction, query, searchColumn, onColumns, onSort }: { table: string; logs: boolean; sort: string; direction: string; query: string; searchColumn: string; onColumns: (columns: string[]) => void; onSort: (column: string) => void }) {
  const [rows, setRows] = useState<Row[]>([])
  const [columns, setColumns] = useState<string[]>([])
  const [cursor, setCursor] = useState<string | number | null>(null)
  const [next, setNext] = useState<string | number | null>(null)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')
  const sentinel = useRef<HTMLDivElement>(null)
  const scrollArea = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const controller = new AbortController()
    setBusy(true)
    const params = new URLSearchParams()
    if (cursor !== null) params.set(logs ? 'cursor' : 'offset', String(cursor))
    if (!logs && sort) { params.set('sort', sort); params.set('direction', direction) }
    if (!logs && query) params.set('q', query)
    if (!logs && searchColumn) params.set('column', searchColumn)
    const path = logs ? '/api/admin/log' : `/api/admin/database/${encodeURIComponent(table)}`
    fetch(`${path}?${params}`, { signal: controller.signal, cache: 'no-store' })
      .then(async response => {
        const data = await response.json()
        if (!response.ok) throw new Error(data.error || '無法載入資料。')
        if (controller.signal.aborted) return
        setRows(previous => cursor === null ? data.rows : [...previous, ...data.rows])
        setColumns(logs ? Object.keys(logFields) : data.columns)
        if (!logs) onColumns(data.columns)
        setNext(logs ? data.nextCursor : data.nextOffset)
      }).catch(error => {
        if (!controller.signal.aborted) { setError(error.message); setRows([]); setNext(null) }
      }).finally(() => { if (!controller.signal.aborted) setBusy(false) })
    return () => controller.abort()
  }, [table, logs, sort, direction, cursor, query, searchColumn, onColumns])
  useEffect(() => {
    const observer = new IntersectionObserver(entries => {
      if (entries[0].isIntersecting && !busy && !error && next !== null) setCursor(next)
    }, { root: logs ? null : scrollArea.current })
    if (sentinel.current) observer.observe(sentinel.current)
    return () => observer.disconnect()
  }, [busy, error, next, logs])
  const pagination = <div ref={sentinel} className="admin-pagination">
    {busy ? <p role="status">載入中…</p> : next !== null ? <button className="account-button" onClick={() => setCursor(next)}>載入更多</button> : rows.length > 0 && <p>已顯示全部紀錄</p>}
  </div>
  return <>
    {error && <p role="alert">{error}</p>}
    {!error && <>
      <p className="admin-count">已載入 {rows.length} 筆{logs && ` · ${Intl.DateTimeFormat().resolvedOptions().timeZone}`}</p>
      <div ref={scrollArea} className="admin-table-scroll" tabIndex={0} aria-label={logs ? '後端紀錄表格' : `${table} 資料表`}>
        <table className="admin-table"><thead><tr>{columns.map(column => <th key={column} aria-sort={!logs && column === sort ? direction === 'asc' ? 'ascending' : 'descending' : undefined}>
          {logs ? logFields[column] : <button onClick={() => onSort(column)}>{column}{sort === column ? direction === 'asc' ? <ArrowUp size={14} /> : <ArrowDown size={14} /> : <ChevronsUpDown size={14} />}</button>}
        </th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index}>{columns.map(column => <td key={column} className={logs && column === 'level' ? `log-level log-${String(row[column]).toLowerCase()}` : ''}>{cell(row[column], column, logs)}</td>)}</tr>)}</tbody></table>
        {!logs && pagination}
      </div>
      {!busy && rows.length === 0 && <p role="status">目前沒有資料。</p>}
      {logs && pagination}
    </>}
  </>
}

/** Display searchable desktop and mobile selectors with server-side content search. */
export default function AdminViewer({ mode }: { mode: 'database' | 'log' }) {
  const logs = mode === 'log'
  const [tables, setTables] = useState<string[]>([])
  const [table, setTable] = useState('')
  const [search, setSearch] = useState('')
  const [contentSearch, setContentSearch] = useState('')
  const [query, setQuery] = useState('')
  const [columns, setColumns] = useState<string[]>([])
  const [searchColumn, setSearchColumn] = useState('')
  const [appliedColumn, setAppliedColumn] = useState('')
  const [searchRevision, setSearchRevision] = useState(0)
  const [sort, setSort] = useState('')
  const [direction, setDirection] = useState('asc')
  const [revision, setRevision] = useState(0)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(!logs)
  useEffect(() => {
    if (logs) return
    const controller = new AbortController()
    setLoading(true); setError('')
    fetch('/api/admin/database', { signal: controller.signal, cache: 'no-store' })
      .then(async response => {
        const data = await response.json()
        if (!response.ok) throw new Error(data.error || '無法載入資料表。')
        if (controller.signal.aborted) return
        setTables(data.tables)
        setTable(previous => data.tables.includes(previous) ? previous : '')
      }).catch(error => { if (!controller.signal.aborted) { setError(error.message); setTables([]); setTable('') } })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [logs, revision])
  const filtered = tables.filter(name => name.toLowerCase().includes(search.toLowerCase()))
  const select = (name: string) => { setTable(name); setSort(''); setDirection('asc'); setContentSearch(''); setQuery(''); setColumns([]); setSearchColumn(''); setAppliedColumn('') }
  return <section className="admin-viewer">
    <Link to="/admin" className="profile-back"><ArrowLeft size={16} aria-hidden="true" />返回管理工具</Link>
    <div className="admin-heading"><h1>{logs ? '後端紀錄' : '資料庫'}</h1><button className="account-button" title="重新整理" aria-label="重新整理" onClick={() => setRevision(value => value + 1)}><RefreshCw size={18} /></button></div>
    {error && <p role="alert">{error}</p>}
    {loading && <p role="status">載入資料表中…</p>}
    {!error && !loading && <div className={logs ? '' : 'admin-database-layout'}>
      {!logs && <aside className="admin-table-picker">
        <label className="admin-search admin-desktop-search"><Search size={17} /><input aria-label="搜尋資料表" placeholder="搜尋資料表" value={search} onChange={event => setSearch(event.target.value)} /></label>
        <div className="admin-mobile-select"><Select aria-label="選取資料表" classNamePrefix="admin-select" options={tables.map(name => ({ value: name, label: name }))} value={table ? { value: table, label: table } : null} onChange={option => select(option?.value || '')} isClearable isSearchable placeholder="搜尋或選取資料表" noOptionsMessage={() => '沒有符合的資料表'} styles={{ container: base => ({ ...base, minWidth: 0, width: '100%' }), control: base => ({ ...base, minWidth: 0, minHeight: 44 }), valueContainer: base => ({ ...base, minWidth: 0 }), menu: base => ({ ...base, width: '100%', zIndex: 20 }), option: base => ({ ...base, overflowWrap: 'anywhere' }) }} /></div>
        <nav className="admin-table-list" aria-label="資料表">{filtered.map(name => <button key={name} aria-current={table === name ? 'true' : undefined} onClick={() => select(name)}>{name}</button>)}</nav>
        {filtered.length === 0 && <p>沒有符合的資料表。</p>}
      </aside>}
      <div className="admin-records">{logs || table ? <><h2>{logs ? '應用程式日誌' : table}</h2>{!logs && <form className="admin-search-form" role="search" onSubmit={event => { event.preventDefault(); setQuery(contentSearch); setAppliedColumn(searchColumn); setSearchRevision(value => value + 1) }}>
        <select aria-label="搜尋範圍" value={searchColumn} onChange={event => setSearchColumn(event.target.value)}><option value="">全部欄位</option>{columns.map(column => <option key={column} value={column}>{column}</option>)}</select>
        <label className="admin-search"><input type="search" aria-label="搜尋欄位內容" placeholder="輸入搜尋內容" maxLength={500} value={contentSearch} onChange={event => setContentSearch(event.target.value)} /></label>
        <button type="submit" className="admin-sync-button"><Search size={17} aria-hidden="true" />搜尋</button>
      </form>}<Records key={`${table}:${sort}:${direction}:${revision}:${searchRevision}`} table={table} logs={logs} sort={sort} direction={direction} query={query} searchColumn={appliedColumn} onColumns={setColumns} onSort={column => { setSort(column); setDirection(column === sort && direction === 'asc' ? 'desc' : 'asc') }} /></> : <p>請選取資料表。</p>}</div>
    </div>}
  </section>
}
