import { useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'
import { btn, input } from '../components/ui'

const DEMO = [['mf1', 'Mulberry farmer'], ['sf1', 'Silkworm farmer'], ['reeler1', 'Reeler'], ['spinner1', 'Spinner']]

export default function Login() {
  const { user, login } = useAuth()
  const nav = useNavigate()
  const [username, setU] = useState('')
  const [password, setP] = useState('')
  const [err, setErr] = useState('')
  if (user) return <Navigate to="/" replace />
  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    try { await login(username, password); nav('/') } catch (x: any) { setErr(x.message) }
  }
  return (
    <div className="grid min-h-screen lg:grid-cols-2">
      <div className="hidden flex-col justify-between bg-gradient-to-br from-[#241a45] to-brand-600 p-12 text-white lg:flex">
        <div className="text-xl font-semibold tracking-tight">Ariadne</div>
        <div>
          <h1 className="text-4xl font-semibold leading-tight tracking-tight">When one link in the silk chain breaks,<br />everyone downstream knows first.</h1>
          <p className="mt-4 max-w-md text-white/70">Agentic triage and dynamic rerouting across mulberry, silkworm, reeling and spinning, with a human approving every deal.</p>
        </div>
        <div className="text-sm text-white/50">Team 14 · Agentic AI</div>
      </div>
      <div className="flex items-center justify-center p-6">
        <form onSubmit={submit} className="w-full max-w-sm">
          <h2 className="text-2xl font-semibold tracking-tight text-ink">Sign in</h2>
          <p className="mb-6 mt-1 text-sm text-slate-500">Use a demo account below or your own.</p>
          <label className="text-sm font-medium text-slate-700">Username</label>
          <input className={`${input} mb-4 mt-1 w-full`} value={username} onChange={e => setU(e.target.value)} autoFocus />
          <label className="text-sm font-medium text-slate-700">Password</label>
          <input type="password" className={`${input} mb-4 mt-1 w-full`} value={password} onChange={e => setP(e.target.value)} />
          {err && <p className="mb-3 text-sm text-red-600">{err}</p>}
          <button className={`${btn.primary} w-full`}>Sign in</button>
          <div className="mt-8 rounded-xl bg-slate-100/70 p-4">
            <p className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-500">Demo accounts · password ariadne123</p>
            <div className="grid grid-cols-2 gap-2">
              {DEMO.map(([u, label]) => (
                <button type="button" key={u} onClick={() => { setU(u); setP('ariadne123') }}
                  className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-left text-sm hover:border-brand-500">
                  <div className="font-medium text-ink">{label}</div><div className="text-xs text-slate-400">{u}</div></button>))}
            </div>
          </div>
        </form>
      </div>
    </div>
  )
}
