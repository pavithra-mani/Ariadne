import { useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth'
import { Icon, Logo } from '../components/ui'

const DEMO: [string, string, string, string][] = [
  ['mf1', 'Mulberry farmer', 'Grows the leaves', 'leaf'],
  ['sf1', 'Silkworm farmer', 'Rears the worms', 'worm'],
  ['reeler1', 'Reeler', 'Turns cocoons to yarn', 'reel'],
  ['spinner1', 'Spinner', 'Twists the thread', 'spin'],
]

/** The chain the product travels, with a gold thread running through it. */
function ChainArt() {
  const nodes: [number, number, string][] = [[70, 292, 'Mulberry'], [190, 214, 'Silkworm'], [320, 150, 'Reeling'], [450, 70, 'Spinning']]
  return (
    <svg viewBox="0 0 540 340" className="w-full max-w-[520px]" fill="none" aria-hidden>
      <defs>
        <linearGradient id="thread" x1="0" y1="1" x2="1" y2="0"><stop offset="0" stopColor="#f4e091" /><stop offset="1" stopColor="#c79a2c" /></linearGradient>
        <radialGradient id="glow"><stop offset="0" stopColor="#ecca5e" stopOpacity="0.35" /><stop offset="1" stopColor="#ecca5e" stopOpacity="0" /></radialGradient>
      </defs>
      {[0, 1, 2, 3].map(i => <ellipse key={i} cx="270" cy="170" rx={90 + i * 55} ry={50 + i * 34} stroke="#ffffff" strokeOpacity={0.05 + 0.01 * (3 - i)} />)}
      <path d="M70 292 C 120 292 140 220 190 214 S 280 170 320 150 S 410 90 450 70" stroke="url(#thread)" strokeWidth="2.5" strokeLinecap="round" strokeDasharray="1 7" />
      <path d="M70 292 C 120 292 140 220 190 214 S 280 170 320 150 S 410 90 450 70" stroke="url(#thread)" strokeWidth="1.2" strokeOpacity="0.55" />
      {nodes.map(([x, y, label], i) => (
        <g key={label}>
          <circle cx={x} cy={y} r="30" fill="url(#glow)" />
          <circle cx={x} cy={y} r="11" fill="#2b1854" stroke="url(#thread)" strokeWidth="2" />
          <circle cx={x} cy={y} r="3.5" fill="#ecca5e" />
          <text x={x} y={y + (i % 2 ? -22 : 30)} textAnchor="middle" fontSize="12" letterSpacing="1.5" fill="#ffffff" fillOpacity="0.8" style={{ textTransform: 'uppercase' }}>{label}</text>
        </g>))}
    </svg>
  )
}

export default function Login() {
  const { user, login } = useAuth()
  const nav = useNavigate()
  const [username, setU] = useState('')
  const [password, setP] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  if (user) return <Navigate to="/" replace />
  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true); setErr('')
    try { await login(username, password); nav('/') } catch (x: any) { setErr(x.message || 'Could not sign in') } finally { setBusy(false) }
  }
  const field = 'mt-1.5 w-full rounded-xl border border-brand-100 bg-white px-4 py-3 text-[15px] text-ink outline-none transition placeholder:text-slate-400 focus:border-brand-400 focus:ring-4 focus:ring-brand-100'
  return (
    <div className="grid min-h-screen lg:grid-cols-[1.1fr_1fr]">
      <div className="relative hidden flex-col justify-between overflow-hidden bg-gradient-to-br from-brand-950 via-brand-900 to-brand-700 p-12 text-white lg:flex">
        <div className="pointer-events-none absolute -right-32 -top-32 h-96 w-96 rounded-full bg-gold-400/10 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-40 -left-20 h-96 w-96 rounded-full bg-brand-400/20 blur-3xl" />
        <Logo size={34} />
        <div className="relative">
          <ChainArt />
          <h1 className="mt-4 max-w-md font-display text-[38px] font-semibold leading-[1.15] tracking-tight">
            When one link in the silk chain breaks, <span className="text-gold-300">everyone downstream knows first.</span>
          </h1>
          <p className="mt-4 max-w-md text-[15px] leading-relaxed text-white/65">
            Ariadne watches the whole chain, from mulberry to thread, finds other sources when something goes wrong and sends the offers. Nothing is bought or sold until both sides say yes.
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs text-white/45"><span className="h-px w-8 bg-gold-400/60" />A human approves every deal</div>
      </div>

      <div className="flex flex-col justify-center px-6 py-10 sm:px-12">
        <div className="mx-auto w-full max-w-[420px]">
          <div className="mb-8 lg:hidden"><Logo light={false} size={30} /></div>
          <h2 className="font-display text-[32px] font-semibold tracking-tight text-ink">Welcome back</h2>
          <div className="mt-2 h-[3px] w-10 rounded-full bg-gradient-to-r from-gold-400 to-gold-200" />
          <p className="mb-7 mt-3 text-sm text-slate-500">Sign in to see your stock, offers and alerts.</p>
          <form onSubmit={submit}>
            <label className="text-sm font-medium text-slate-700" htmlFor="u">Username</label>
            <input id="u" className={field} value={username} onChange={e => setU(e.target.value)} autoFocus autoComplete="username" placeholder="e.g. sf1" />
            <label className="mt-4 block text-sm font-medium text-slate-700" htmlFor="p">Password</label>
            <input id="p" type="password" className={field} value={password} onChange={e => setP(e.target.value)} autoComplete="current-password" placeholder="Your password" />
            {err && <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{err}</p>}
            <button disabled={busy || !username || !password} className="mt-6 w-full rounded-xl bg-gradient-to-b from-brand-500 to-brand-700 py-3 text-[15px] font-semibold text-white shadow-[0_10px_24px_-10px_rgba(80,48,154,0.7)] transition hover:from-brand-600 hover:to-brand-800 active:translate-y-px disabled:opacity-50">
              {busy ? 'Signing in…' : 'Sign in'}
            </button>
          </form>

          <div className="mt-9">
            <div className="mb-3 flex items-center gap-3 text-[11px] font-semibold uppercase tracking-[0.14em] text-gold-600">
              <span>Try a demo account</span><span className="h-px flex-1 bg-gold-200" /><span className="font-normal normal-case tracking-normal text-slate-400">password: ariadne123</span>
            </div>
            <div className="grid grid-cols-2 gap-2.5">
              {DEMO.map(([u, label, sub]) => (
                <button type="button" key={u} onClick={() => { setU(u); setP('ariadne123') }}
                  className={`group rounded-2xl border bg-white p-3.5 text-left shadow-soft transition hover:-translate-y-0.5 hover:border-brand-300 hover:shadow-lift ${username === u ? 'border-brand-400 ring-4 ring-brand-100' : 'border-brand-100'}`}>
                  <div className="flex items-center justify-between"><span className="text-sm font-semibold text-ink">{label}</span><Icon name="chain" className="h-4 w-4 text-gold-500 opacity-0 transition group-hover:opacity-100" /></div>
                  <div className="mt-0.5 text-xs text-slate-500">{sub}</div>
                  <div className="mt-2 text-[11px] font-medium text-brand-600">{u}</div>
                </button>))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
