import { useEffect, useState } from 'react'
import { NavLink, Navigate, Outlet, Route, Routes, useLocation } from 'react-router-dom'
import { api } from './api'
import { useAuth } from './auth'
import { Icon } from './components/ui'
import Alerts from './pages/Alerts'
import Approvals from './pages/Approvals'
import Chat from './pages/Chat'
import Dashboard from './pages/Dashboard'
import Deals from './pages/Deals'
import Eval from './pages/Eval'
import Incidents from './pages/Incidents'
import Knowledge from './pages/Knowledge'
import Login from './pages/Login'
import System from './pages/System'
import { ROLE_LABEL } from './types'

const MAIN: [string, string, string][] = [
  ['/', 'Dashboard', 'home'], ['/assistant', 'Assistant', 'chat'], ['/alerts', 'Alerts', 'bell'],
  ['/incidents', 'Incidents', 'flag'], ['/approvals', 'Approvals', 'check'], ['/deals', 'Deals & ledger', 'deals'],
  ['/knowledge', 'Knowledge', 'book'],
]
const MORE: [string, string, string][] = [['/system', 'System', 'cog'], ['/eval', 'Evaluation', 'chart']]

function Shell() {
  const { user, loading, logout } = useAuth()
  const [badge, setBadge] = useState<Record<string, number>>({})
  const loc = useLocation()
  useEffect(() => {
    if (!user) return
    const load = async () => {
      try {
        const [ap, no] = await Promise.all([api('/api/approvals'), api('/api/notifications')])
        setBadge({ '/approvals': ap.length, '/alerts': no.filter((n: any) => !n.read).length })
      } catch { /* ignore transient errors */ }
    }
    load()
    const t = setInterval(load, 8000)
    return () => clearInterval(t)
  }, [user, loc.pathname])
  if (loading) return null
  if (!user) return <Navigate to="/login" replace />

  const item = ([to, label, icon]: [string, string, string]) => (
    <NavLink key={to} to={to} end={to === '/'} className={({ isActive }) =>
      `flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition ${isActive ? 'bg-white/15 font-medium text-white' : 'text-white/65 hover:bg-white/8 hover:text-white'}`}>
      <Icon name={icon} className="h-[18px] w-[18px]" /><span className="flex-1">{label}</span>
      {!!badge[to] && <span className="rounded-full bg-red-500 px-1.5 text-[11px] font-semibold text-white">{badge[to]}</span>}
    </NavLink>
  )
  return (
    <div className="min-h-screen">
      <aside className="fixed inset-y-0 left-0 z-10 flex w-60 flex-col bg-gradient-to-b from-[#241a45] to-[#1a1233] px-3 py-5">
        <div className="mb-8 px-3 text-xl font-semibold tracking-tight text-white">Ariadne</div>
        <nav className="space-y-0.5">{MAIN.map(item)}</nav>
        <div className="mb-1 mt-6 px-3 text-[11px] font-medium uppercase tracking-wider text-white/35">More</div>
        <nav className="space-y-0.5">{MORE.map(item)}</nav>
        <div className="mt-auto rounded-xl bg-white/8 p-3">
          <div className="truncate text-sm font-medium text-white">{user.entity_name}</div>
          <div className="text-xs text-white/55">{ROLE_LABEL[user.role]} · {user.village}</div>
          <button onClick={logout} className="mt-2 text-xs text-white/60 hover:text-white">Sign out</button>
        </div>
      </aside>
      <main className="ml-60 min-h-screen"><div className="mx-auto max-w-5xl px-8 py-8"><Outlet /></div></main>
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
        <Route path="/knowledge" element={<Knowledge />} />
        <Route path="/system" element={<System />} />
        <Route path="/eval" element={<Eval />} />
      </Route>
    </Routes>
  )
}
