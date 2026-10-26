import type { ReactNode } from 'react'

export const inr = (n: number) => '₹' + Number(n).toLocaleString('en-IN', { maximumFractionDigits: 0 })
export const kg = (n: number, d = 0) => Number(n).toLocaleString('en-IN', { maximumFractionDigits: d })
export const days = (n: number, d = 1) => (n >= 999 ? '∞' : Number(n).toLocaleString('en-IN', { maximumFractionDigits: d }))

const PATHS: Record<string, string> = {
  chain: 'M3 6.75A2.25 2.25 0 015.25 4.5h2.5A2.25 2.25 0 0110 6.75v.5A2.25 2.25 0 017.75 9.5h-2.5A2.25 2.25 0 013 7.25v-.5zM14 16.75a2.25 2.25 0 012.25-2.25h2.5A2.25 2.25 0 0121 16.75v.5a2.25 2.25 0 01-2.25 2.25h-2.5A2.25 2.25 0 0114 17.25v-.5zM10 7h2.5a2.5 2.5 0 012.5 2.5v5M15 14.5l-1.75-1.75M15 14.5l1.75-1.75',
  camera: 'M6.827 6.175A2.31 2.31 0 015.186 7.23c-.38.054-.757.112-1.134.175C2.999 7.58 2.25 8.507 2.25 9.574V18a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9.574c0-1.067-.75-1.994-1.802-2.169a47.865 47.865 0 00-1.134-.175 2.31 2.31 0 01-1.64-1.055l-.822-1.316a2.192 2.192 0 00-1.736-1.039 48.774 48.774 0 00-5.232 0 2.192 2.192 0 00-1.736 1.039l-.821 1.316zM16.5 12.75a4.5 4.5 0 11-9 0 4.5 4.5 0 019 0z',
  dots: 'M6.75 12a.75.75 0 11-1.5 0 .75.75 0 011.5 0zM12.75 12a.75.75 0 11-1.5 0 .75.75 0 011.5 0zM18.75 12a.75.75 0 11-1.5 0 .75.75 0 011.5 0z',
  home: 'M2.25 12l8.954-8.955a1.126 1.126 0 011.591 0L21.75 12M4.5 9.75v10.125c0 .621.504 1.125 1.125 1.125H9.75v-4.875c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125V21h4.125c.621 0 1.125-.504 1.125-1.125V9.75M8.25 21h8.25',
  chat: 'M8.625 12a.375.375 0 11-.75 0 .375.375 0 01.75 0zm4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm4.125 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zM2.25 12.76c0 1.6 1.123 2.994 2.707 3.227 1.087.16 2.185.283 3.293.369V21l4.076-4.076a1.526 1.526 0 011.037-.443 48.282 48.282 0 005.68-.494c1.584-.233 2.707-1.626 2.707-3.228V6.741c0-1.602-1.123-2.995-2.707-3.228A48.394 48.394 0 0012 3c-2.392 0-4.744.175-7.043.513C3.373 3.746 2.25 5.14 2.25 6.741v6.018z',
  alert: 'M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z',
  check: 'M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z',
  doc: 'M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z',
  book: 'M12 6.042A8.967 8.967 0 006 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 8.987 0 016 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 016-2.292c1.052 0 2.062.18 3 .512v14.25A8.987 8.987 0 0018 18a8.967 8.967 0 00-6 2.292m0-14.25v14.25',
  bell: 'M14.857 17.082a23.848 23.848 0 005.454-1.31A8.967 8.967 0 0118 9.75v-.7V9A6 6 0 006 9v.75a8.967 8.967 0 01-2.312 6.022c1.733.64 3.56 1.085 5.455 1.31m5.714 0a24.255 24.255 0 01-5.714 0m5.714 0a3 3 0 11-5.714 0',
  cog: 'M10.343 3.94c.09-.542.56-.94 1.11-.94h1.093c.55 0 1.02.398 1.11.94l.149.894c.07.424.384.764.78.93.398.164.855.142 1.205-.108l.737-.527a1.125 1.125 0 011.45.12l.773.774c.39.389.44 1.002.12 1.45l-.527.737c-.25.35-.272.806-.107 1.204.165.397.505.71.93.78l.893.15c.543.09.94.56.94 1.109v1.094c0 .55-.397 1.02-.94 1.11l-.893.149c-.425.07-.765.383-.93.78-.165.398-.143.854.107 1.204l.527.738c.32.447.269 1.06-.12 1.45l-.774.773a1.125 1.125 0 01-1.449.12l-.738-.527c-.35-.25-.806-.272-1.203-.107-.397.165-.71.505-.781.929l-.149.894c-.09.542-.56.94-1.11.94h-1.094c-.55 0-1.019-.398-1.11-.94l-.148-.894c-.071-.424-.384-.764-.781-.93-.398-.164-.854-.142-1.204.108l-.738.527c-.447.32-1.06.269-1.45-.12l-.773-.774a1.125 1.125 0 01-.12-1.45l.527-.737c.25-.35.273-.806.108-1.204-.165-.397-.505-.71-.93-.78l-.894-.15c-.542-.09-.94-.56-.94-1.109v-1.094c0-.55.398-1.02.94-1.11l.894-.149c.424-.07.765-.383.93-.78.165-.398.143-.854-.107-1.204l-.527-.738a1.125 1.125 0 01.12-1.45l.773-.773a1.125 1.125 0 011.45-.12l.737.527c.35.25.807.272 1.204.107.397-.165.71-.505.78-.929l.15-.894z M15 12a3 3 0 11-6 0 3 3 0 016 0z',
  chart: 'M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z',
  deals: 'M7.5 21L3 16.5m0 0L7.5 12M3 16.5h13.5m0-13.5L21 7.5m0 0L16.5 12M21 7.5H7.5',
  flag: 'M3 3v1.5M3 21v-6m0 0l2.77-.693a9 9 0 016.208.682l.108.054a9 9 0 006.086.71l3.114-.732a48.524 48.524 0 01-.005-10.499l-3.11.732a9 9 0 01-6.085-.711l-.108-.054a9 9 0 00-6.208-.682L3 4.5M3 15V4.5',
}

export function Icon({ name, className = 'h-5 w-5' }: { name: string; className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" strokeWidth={1.6} stroke="currentColor" aria-hidden>
      <path strokeLinecap="round" strokeLinejoin="round" d={PATHS[name] ?? PATHS.doc} />
    </svg>
  )
}

const TONES: Record<string, string> = {
  ok: 'bg-emerald-50 text-emerald-700 ring-emerald-200', reorder: 'bg-gold-50 text-gold-700 ring-gold-200',
  critical: 'bg-red-50 text-red-700 ring-red-200', degrading: 'bg-orange-50 text-orange-700 ring-orange-200',
  slate: 'bg-slate-100 text-slate-600 ring-slate-200', violet: 'bg-brand-50 text-brand-700 ring-brand-200',
  gold: 'bg-gold-50 text-gold-700 ring-gold-200',
  blue: 'bg-sky-50 text-sky-700 ring-sky-200',
}

export function Badge({ tone = 'slate', children }: { tone?: string; children: ReactNode }) {
  return <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${TONES[tone] ?? TONES.slate}`}>{children}</span>
}

export function Card({ title, subtitle, right, children, className = '', pad = true }:
  { title?: ReactNode; subtitle?: ReactNode; right?: ReactNode; children: ReactNode; className?: string; pad?: boolean }) {
  return (
    <section className={`rounded-2xl border border-brand-100/80 bg-white shadow-soft ${className}`}>
      {(title || right) && (
        <header className="flex items-start justify-between gap-3 px-5 pt-4">
          <div><h2 className="font-display text-[16px] font-semibold text-ink">{title}</h2>{subtitle && <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>}</div>{right}
        </header>
      )}
      <div className={pad ? 'p-5' : ''}>{children}</div>
    </section>
  )
}

export function PageHeader({ title, subtitle, right }: { title: string; subtitle?: ReactNode; right?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div><h1 className="font-display text-[28px] font-semibold leading-tight tracking-tight text-ink">{title}</h1><div className="mt-2 h-[3px] w-10 rounded-full bg-gradient-to-r from-gold-400 to-gold-200" />{subtitle && <p className="mt-2.5 text-sm text-slate-500">{subtitle}</p>}</div>{right}
    </div>
  )
}

export function Stat({ label, value, sub, bar, tone = 'brand' }: { label: string; value: ReactNode; sub?: ReactNode; bar?: number; tone?: string }) {
  const c = tone === 'red' ? 'bg-red-500' : tone === 'amber' ? 'bg-gold-400' : 'bg-gradient-to-r from-brand-500 to-brand-400'
  return (
    <div className="rounded-2xl border border-brand-100/80 bg-white p-5 shadow-soft">
      <div className="text-xs font-medium uppercase tracking-wide text-slate-400">{label}</div>
      <div className="mt-1.5 text-2xl font-semibold tracking-tight text-ink">{value}</div>
      {bar !== undefined && <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-slate-100"><div className={`h-full rounded-full ${c}`} style={{ width: `${Math.min(bar * 100, 100)}%` }} /></div>}
      {sub && <div className="mt-2 text-xs text-slate-500">{sub}</div>}
    </div>
  )
}

export function Empty({ icon = 'doc', title, children }: { icon?: string; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center py-10 text-center">
      <div className="mb-3 rounded-full bg-brand-50 p-3 text-brand-400"><Icon name={icon} className="h-6 w-6" /></div>
      <div className="text-sm font-medium text-slate-700">{title}</div>
      {children && <div className="mt-1 max-w-md text-sm text-slate-500">{children}</div>}
    </div>
  )
}

export const btn = {
  primary: 'inline-flex items-center justify-center rounded-xl bg-gradient-to-b from-brand-500 to-brand-700 px-4 py-2 text-sm font-medium text-white shadow-[0_6px_16px_-6px_rgba(80,48,154,0.55)] transition hover:from-brand-600 hover:to-brand-800 hover:shadow-[0_8px_20px_-6px_rgba(80,48,154,0.6)] active:translate-y-px disabled:opacity-50',
  gold: 'inline-flex items-center justify-center rounded-xl bg-gradient-to-b from-gold-300 to-gold-500 px-4 py-2 text-sm font-semibold text-brand-950 shadow-[0_6px_16px_-6px_rgba(167,123,34,0.6)] transition hover:from-gold-300 hover:to-gold-600 active:translate-y-px disabled:opacity-50',
  ghost: 'inline-flex items-center justify-center rounded-xl border border-brand-200 bg-white px-3 py-1.5 text-sm font-medium text-brand-800 transition hover:border-brand-300 hover:bg-brand-50 disabled:opacity-50',
  good: 'inline-flex items-center justify-center rounded-xl bg-emerald-600 px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-emerald-700 disabled:opacity-50',
  bad: 'inline-flex items-center justify-center rounded-xl border border-red-200 bg-white px-4 py-2 text-sm font-medium text-red-600 transition hover:bg-red-50 disabled:opacity-50',
}
export const input = 'rounded-xl border border-brand-100 bg-white px-3.5 py-2.5 text-sm outline-none transition placeholder:text-slate-400 focus:border-brand-400 focus:ring-4 focus:ring-brand-100'

export function Tabs({ tabs, value, onChange }: { tabs: [string, string, number?][]; value: string; onChange: (v: string) => void }) {
  return (
    <div className="mb-4 inline-flex rounded-xl bg-brand-100/60 p-1">
      {tabs.map(([k, label, n]) => (
        <button key={k} onClick={() => onChange(k)} className={`rounded-lg px-4 py-1.5 text-sm font-medium transition ${value === k ? 'bg-white text-brand-800 shadow-soft' : 'text-slate-500 hover:text-brand-700'}`}>
          {label}{n !== undefined && <span className="ml-1.5 rounded-full bg-slate-100 px-1.5 text-xs text-slate-500">{n}</span>}
        </button>))}
    </div>
  )
}

/** Brand mark: a cocoon wrapped in a gold thread. */
export function Logo({ size = 28, text = true, light = true }: { size?: number; text?: boolean; light?: boolean }) {
  return (
    <span className="inline-flex items-center gap-2.5">
      <svg width={size} height={size} viewBox="0 0 32 32" fill="none" aria-hidden>
        <ellipse cx="16" cy="16" rx="9" ry="12.5" fill={light ? '#ffffff22' : '#6540b61a'} stroke={light ? '#ffffffaa' : '#6540b6'} strokeWidth="1.4" />
        <path d="M3 24 C 9 24, 8 12, 16 14 S 23 22, 29 8" stroke="#e0b23a" strokeWidth="2" strokeLinecap="round" />
        <circle cx="29" cy="8" r="2" fill="#e0b23a" />
      </svg>
      {text && <span className={`font-display text-[22px] font-semibold tracking-tight ${light ? 'text-white' : 'text-brand-900'}`}>Ariadne</span>}
    </span>
  )
}
