import { useEffect, useState } from 'react'
import { NavLink, Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom'
import { api } from './api'
import { useAuth } from './auth'
import { Icon, Logo } from './components/ui'
import { FARMER_MAIN, FARMER_MORE, FULL_MAIN, FULL_MORE } from './nav'
import Alerts from './pages/Alerts'
import Approvals from './pages/Approvals'
import Chain from './pages/Chain'
import Chat from './pages/Chat'
import Dashboard from './pages/Dashboard'
import Deals from './pages/Deals'
import Eval from './pages/Eval'
import Incidents from './pages/Incidents'
import Knowledge from './pages/Knowledge'
import Login from './pages/Login'
import System from './pages/System'
import { ROLE_LABEL, isFarmer, type NavItem } from './types'

function Shell() {
  const { user, loading, logout } = useAuth()
  const [badge, setBadge] = useState<Record<string, number>>({})
  const [sheet, setSheet] = useState(false)
  const loc = useLocation()
  useEffect(() => {
    if (!user) return
    const load = async () => {
      try {
        const [ap, no] = await Promise.all([api('/api/approvals'), api('/api/notifications')])
        setBadge({ approvals: ap.length, alerts: no.filter((n: any) => !n.read).length })
      } catch { /* ignore transient errors */ }
    }
    load()
    const t = setInterval(load, 8000)
    return () => clearInterval(t)
  }, [user, loc.pathname])
  useEffect(() => setSheet(false), [loc.pathname])
  if (loading) return null
  if (!user) return <Navigate to="/login" replace />

  const farmer = isFarmer(user.role)
  const main = farmer ? FARMER_MAIN : FULL_MAIN
  const more = farmer ? FARMER_MORE : FULL_MORE
  const bar = farmer ? FARMER_MAIN : FULL_MAIN.filter(i => ['/', '/assistant', '/approvals', '/alerts', '/chain'].includes(i.to))
  const inBar = new Set(bar.map(i => i.to))
  const sheetItems = [...main, ...more].filter(i => !inBar.has(i.to))
  const count = (i: NavItem) => (i.badge ? badge[i.badge] : 0)

  const item = (i: NavItem) => (
    <NavLink key={i.to} to={i.to} end={i.to === '/'} className={({ isActive }) =>
      `group relative flex items-start gap-3 rounded-xl px-3 py-2 transition ${isActive ? 'bg-white/12 text-white shadow-[inset_0_0_0_1px_rgba(255,255,255,0.08)]' : 'text-white/65 hover:bg-white/[0.07] hover:text-white'}`}>
      <Icon name={i.icon} className="mt-0.5 h-[18px] w-[18px] shrink-0 group-[.active]:text-gold-300" />
      <span className="min-w-0 flex-1"><span className="block text-sm font-medium leading-tight">{i.label}</span><span className="mt-0.5 block text-[11px] font-normal leading-snug text-white/45">{i.desc}</span></span>
      {!!count(i) && <span className="rounded-full bg-gold-400 px-1.5 text-[11px] font-bold text-brand-950">{count(i)}</span>}
    </NavLink>
  )
  return (
    <div className="min-h-screen">
      <aside className="fixed inset-y-0 left-0 z-10 hidden w-64 flex-col bg-gradient-to-b from-brand-800 via-brand-900 to-brand-950 px-3 py-5 shadow-[1px_0_0_0_rgba(223,178,60,0.25)] md:flex">
        <div className="mb-7 px-3"><Logo /></div>
        <div className="-mx-1 min-h-0 flex-1 overflow-y-auto px-1 [scrollbar-width:thin] [scrollbar-color:rgba(255,255,255,0.2)_transparent]">
          <nav className="space-y-0.5">{main.map(item)}</nav>
          <div className="mb-1 mt-5 px-3 text-[11px] font-medium uppercase tracking-wider text-gold-300/70">More</div>
          <nav className="space-y-0.5">{more.map(item)}</nav>
        </div>
        <div className="mt-3 shrink-0 rounded-2xl bg-white/[0.07] p-3 ring-1 ring-white/10">
          <div className="truncate text-sm font-medium text-white">{user.entity_name}</div>
          <div className="text-xs text-white/55">{ROLE_LABEL[user.role]} · {user.village}</div>
          <button onClick={logout} className="mt-2 text-xs text-white/60 hover:text-white">Sign out</button>
        </div>
      </aside>

      <header className="sticky top-0 z-10 flex items-center justify-between bg-gradient-to-r from-brand-900 to-brand-800 px-4 py-3 shadow-[0_1px_0_0_rgba(223,178,60,0.3)] md:hidden">
        <Logo size={24} />
        <span className="max-w-[60%] truncate text-xs text-white/70">{user.entity_name}</span>
      </header>
      <main className="min-h-screen pb-24 md:ml-64 md:pb-0"><div className="mx-auto max-w-5xl px-4 py-5 md:px-8 md:py-8"><Outlet /></div></main>

      <nav className="fixed inset-x-0 bottom-0 z-20 flex border-t border-brand-100 bg-white/95 backdrop-blur md:hidden">
        {bar.map(i => (
          <NavLink key={i.to} to={i.to} end={i.to === '/'} className={({ isActive }) =>
            `relative flex flex-1 flex-col items-center gap-0.5 py-2 text-[11px] font-medium ${isActive ? 'text-brand-700' : 'text-slate-500'}`}>
            <Icon name={i.icon} className="h-6 w-6" />{i.label.replace('Report a problem', 'Report').replace('Ask a question', 'Ask')}
            {!!count(i) && <span className="absolute right-1/4 top-1 rounded-full bg-gold-400 px-1.5 text-[10px] font-bold text-brand-950">{count(i)}</span>}
          </NavLink>))}
        <button onClick={() => setSheet(true)} className="flex flex-1 flex-col items-center gap-0.5 py-2 text-[11px] font-medium text-slate-500"><Icon name="dots" className="h-6 w-6" />More</button>
      </nav>
      {sheet && (
        <div className="fixed inset-0 z-30 md:hidden" onClick={() => setSheet(false)}>
          <div className="absolute inset-0 bg-black/40" />
          <div className="absolute inset-x-0 bottom-0 max-h-[80vh] overflow-y-auto rounded-t-2xl bg-white p-4" onClick={e => e.stopPropagation()}>
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">More</div>
            {sheetItems.map(i => (
              <NavLink key={i.to} to={i.to} className="flex items-center gap-3 rounded-xl px-2 py-3 active:bg-slate-50">
                <Icon name={i.icon} className="h-6 w-6 text-brand-600" /><div><div className="text-base font-medium text-ink">{i.label}</div><div className="text-xs text-slate-500">{i.desc}</div></div>
              </NavLink>))}
            <button onClick={logout} className="mt-2 w-full rounded-xl border border-slate-200 py-3 text-base text-slate-600">Sign out ({user.entity_name})</button>
          </div>
        </div>)}
    </div>
  )
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<Shell />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/assistant" element={<Chat />} />
        <Route path="/alerts" element={<Alerts />} />
        <Route path="/incidents" element={<Incidents />} />
        <Route path="/approvals" element={<Approvals />} />
        <Route path="/deals" element={<Deals />} />
        <Route path="/chain" element={<Chain />} />
        <Route path="/knowledge" element={<Knowledge />} />
        <Route path="/system" element={<System />} />
        <Route path="/eval" element={<Eval />} />
      </Route>
    </Routes>
  )
}
