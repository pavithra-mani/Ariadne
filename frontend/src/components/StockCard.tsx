import { useState } from 'react'
import { post } from '../api'
import type { Stock } from '../types'
import { Badge, btn, days, input, kg } from './ui'

const STATUS_TEXT: Record<string, string> = { ok: 'Healthy', reorder: 'Reorder now', critical: 'Below safety stock', degrading: 'Degrading soon' }

/** Level bar: fill = on hand, red zone = safety stock, marker = reorder point. */
function LevelBar({ s }: { s: Stock }) {
  const max = Math.max(s.on_hand, s.reorder_point * 1.5, 1)
  const pct = (x: number) => `${Math.min((x / max) * 100, 100)}%`
  const fill = s.status === 'critical' ? 'bg-red-500' : s.status === 'reorder' ? 'bg-amber-500' : s.status === 'degrading' ? 'bg-orange-400' : 'bg-emerald-500'
  return (
    <div className="relative mt-3 h-2 rounded-full bg-slate-100">
      <div className="absolute inset-y-0 left-0 rounded-full bg-red-100" style={{ width: pct(s.safety_stock) }} />
      <div className={`absolute inset-y-0 left-0 rounded-full ${fill}`} style={{ width: pct(s.on_hand) }} />
      <div className="absolute -top-1 h-4 w-0.5 bg-slate-500" style={{ left: pct(s.reorder_point) }} title={`Reorder point ${kg(s.reorder_point)} kg`} />
    </div>
  )
}

export default function StockCard({ s, editable, onSaved, onIncident, compact }: { s: Stock; editable?: boolean; onSaved?: () => void; onIncident?: (r: any, product: string) => void; compact?: boolean }) {
  const [fixing, setFixing] = useState(false)
  const [open, setOpen] = useState(false)
  const [mode, setMode] = useState<'delta' | 'set_to'>('delta')
  const [qty, setQty] = useState('')
  const [demand, setDemand] = useState('')
  const [msg, setMsg] = useState('')

  const save = async (e: React.FormEvent) => {
    e.preventDefault()
    const body: Record<string, unknown> = { product: s.product, note: 'manual entry from dashboard' }
    if (qty !== '') body[mode] = Number(qty)
    if (demand !== '') body.daily_demand = Number(demand)
    try {
      const r = await post('/api/stock', body)
      setQty(''); setDemand(''); setOpen(false); setMsg(''); onSaved?.()
      if (r.incident || r.buyer_incidents?.length) onIncident?.({ ...(r.incident ?? {}), buyer_incidents_list: r.buyer_incidents ?? [] }, s.product)
    } catch (x: any) { setMsg(x.message) }
  }

  const fix = async () => {
    setFixing(true); setMsg('')
    try { const r = await post(`/api/stock/${s.product}/replenish`); onIncident?.(r, s.product); onSaved?.() }
    catch (x: any) { setMsg(x.message) } finally { setFixing(false) }
  }

  return (
    <div className="rounded-xl border border-slate-200/80 bg-white p-4">
      <div className="flex items-start justify-between">
        <div>
          <div className="text-sm font-medium capitalize text-ink">{s.product} {!s.is_finished && <span className="text-xs font-normal text-slate-400">· raw input</span>}</div>
          <div className="mt-1 text-2xl font-semibold tracking-tight text-ink">{kg(s.on_hand)}<span className="ml-1 text-sm font-normal text-slate-400">kg</span></div>
        </div>
        <Badge tone={s.status}>{STATUS_TEXT[s.status]}</Badge>
      </div>
      <LevelBar s={s} />
      <div className={`mt-3 grid gap-x-4 gap-y-1 text-xs text-slate-500 ${compact ? 'grid-cols-2' : 'grid-cols-2 sm:grid-cols-4'}`}>
        <div>Safety <b className="text-slate-700">{kg(s.safety_stock)}</b></div>
        <div>Reorder at <b className="text-slate-700">{kg(s.reorder_point)}</b></div>
        <div>Sellable <b className="text-slate-700">{s.is_finished ? kg(s.sellable) : '—'}</b></div>
        <div>Cover <b className="text-slate-700">{days(s.days_of_cover)} d</b></div>
        {!compact && <div>Degrades in <b className="text-slate-700">{days(s.degrades_in_days, 0)} d</b></div>}
        {!compact && s.reserved > 0 && <div>Reserved <b className="text-slate-700">{kg(s.reserved)}</b></div>}
      </div>
      {editable && s.status !== 'ok' && (
        <button onClick={fix} disabled={fixing} className="mt-3 w-full rounded-lg bg-brand-600 px-3 py-2 text-sm font-medium text-white transition hover:bg-brand-700 disabled:opacity-60">
          {fixing ? 'Ariadne is working…' : s.is_finished ? 'Ask Ariadne to protect my buyers' : 'Ask Ariadne to restock this'}</button>
      )}
      {editable && (
        <div className="mt-3 border-t border-slate-100 pt-3">
          {!open ? <button onClick={() => setOpen(true)} className="text-xs font-medium text-brand-600 hover:underline">Update stock</button> : (
            <form onSubmit={save} className="flex flex-wrap items-center gap-2">
              <select className={`${input} py-1.5 text-xs`} value={mode} onChange={e => setMode(e.target.value as any)}>
                <option value="delta">± change</option><option value="set_to">set to</option></select>
              <input className={`${input} w-24 py-1.5 text-xs`} type="number" placeholder="kg" value={qty} onChange={e => setQty(e.target.value)} />
              <input className={`${input} w-28 py-1.5 text-xs`} type="number" placeholder="kg/day demand" value={demand} onChange={e => setDemand(e.target.value)} />
              <button className={`${btn.primary} px-3 py-1.5 text-xs`}>Save</button>
              <button type="button" onClick={() => setOpen(false)} className="text-xs text-slate-400">Cancel</button>
              {msg && <span className="text-xs text-red-600">{msg}</span>}
            </form>)}
          {!open && msg && <span className="ml-2 text-xs text-red-600">{msg}</span>}
        </div>
      )}
    </div>
  )
}
