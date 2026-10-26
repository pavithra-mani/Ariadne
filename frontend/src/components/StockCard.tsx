import { useState } from 'react'
import { post } from '../api'
import { FRIENDLY_STATUS, type Stock } from '../types'
import { Badge, btn, days, input, kg } from './ui'

const STATUS_TEXT: Record<string, string> = { ok: 'Healthy', reorder: 'Reorder now', critical: 'Below safety stock', degrading: 'Degrading soon' }

/** Level bar: fill = on hand, red zone = safety stock, marker = reorder point. */
function LevelBar({ s }: { s: Stock }) {
  const max = Math.max(s.on_hand, s.reorder_point * 1.5, 1)
  const pct = (x: number) => `${Math.min((x / max) * 100, 100)}%`
  const fill = s.status === 'critical' ? 'bg-red-500' : s.status === 'reorder' ? 'bg-gold-500' : s.status === 'degrading' ? 'bg-orange-400' : 'bg-emerald-500'
  return (
    <div className="relative mt-3 h-2 rounded-full bg-slate-100">
      <div className="absolute inset-y-0 left-0 rounded-full bg-red-100" style={{ width: pct(s.safety_stock) }} />
      <div className={`absolute inset-y-0 left-0 rounded-full ${fill}`} style={{ width: pct(s.on_hand) }} />
      <div className="absolute -top-1 h-4 w-0.5 bg-slate-500" style={{ left: pct(s.reorder_point) }} title={`Reorder point ${kg(s.reorder_point)} kg`} />
    </div>
  )
}

export default function StockCard({ s, editable, onSaved, onIncident, compact, simple }: { s: Stock; editable?: boolean; onSaved?: () => void; onIncident?: (r: any, product: string) => void; compact?: boolean; simple?: boolean }) {
  const [fixing, setFixing] = useState(false)
  const [open, setOpen] = useState(false)
  const [mode, setMode] = useState<'delta' | 'set_to'>('delta')
  const [qty, setQty] = useState('')
  const [demand, setDemand] = useState('')
  const [msg, setMsg] = useState('')
  const [note, setNote] = useState('')
  const [details, setDetails] = useState(false)

  const save = async (e: React.FormEvent) => {
    e.preventDefault()
    const body: Record<string, unknown> = { product: s.product, note: 'manual entry from dashboard' }
    if (qty !== '') body[mode] = Number(qty)
    if (demand !== '') body.daily_demand = Number(demand)
    try {
      const r = await post('/api/stock', body)
      setQty(''); setDemand(''); setOpen(false); setMsg(''); onSaved?.()
      if (r.agent === 'queued') {  // the guardian agent works in the background: refresh once it has had time to act
        setNote('Ariadne is checking who is affected and will send offers by itself.')
        setTimeout(() => onSaved?.(), 4000); setTimeout(() => { onSaved?.(); setNote('') }, 10000)
      }
      if (r.incident || r.buyer_incidents?.length) onIncident?.({ ...(r.incident ?? {}), buyer_incidents_list: r.buyer_incidents ?? [] }, s.product)
    } catch (x: any) { setMsg(x.message) }
  }

  const fix = async () => {
    setFixing(true); setMsg('')
    try { const r = await post(`/api/stock/${s.product}/replenish`); onIncident?.(r, s.product); onSaved?.() }
    catch (x: any) { setMsg(x.message) } finally { setFixing(false) }
  }

  const [friendly, ftone] = FRIENDLY_STATUS[s.status]
  const cover = s.days_of_cover >= 999 ? 'No use recorded' : `About ${days(s.days_of_cover, 0)} day${Math.round(s.days_of_cover) === 1 ? '' : 's'} left at your usual use`
  const form = editable && (
    <div className={simple ? 'mt-4' : 'mt-3 border-t border-slate-100 pt-3'}>
      {note && <p className="mb-2 rounded-lg bg-brand-50 px-3 py-2 text-sm text-brand-700">{note}</p>}
      {!open ? <button onClick={() => setOpen(true)} className={simple ? 'text-base font-medium text-brand-600' : 'text-xs font-medium text-brand-600 hover:underline'}>Update my stock</button> : (
        <form onSubmit={save} className="flex flex-wrap items-center gap-2">
          <select className={`${input} ${simple ? 'text-base' : 'py-1.5 text-xs'}`} value={mode} onChange={e => setMode(e.target.value as any)}>
            <option value="delta">± change</option><option value="set_to">set to</option></select>
          <input className={`${input} w-24 ${simple ? 'text-base' : 'py-1.5 text-xs'}`} type="number" placeholder="kg" value={qty} onChange={e => setQty(e.target.value)} />
          {!simple && <input className={`${input} w-28 py-1.5 text-xs`} type="number" placeholder="kg/day demand" value={demand} onChange={e => setDemand(e.target.value)} />}
          <button className={`${btn.primary} ${simple ? 'px-5 py-2.5 text-base' : 'px-3 py-1.5 text-xs'}`}>Save</button>
          <button type="button" onClick={() => setOpen(false)} className="text-sm text-slate-400">Cancel</button>
          {msg && <span className="text-xs text-red-600">{msg}</span>}
        </form>)}
      {!open && msg && <span className="ml-2 text-xs text-red-600">{msg}</span>}
    </div>)
  if (simple) return (
    <div className="rounded-2xl border border-brand-100/80 bg-white p-5">
      <div className="flex items-start justify-between gap-2">
        <div><div className="text-lg font-semibold capitalize text-ink">{s.product}</div>
          <div className="mt-1 text-3xl font-semibold tracking-tight text-ink">{kg(s.on_hand)}<span className="ml-1 text-base font-normal text-slate-400">kg</span></div></div>
        <span className={`rounded-full px-3 py-1 text-sm font-semibold ring-1 ring-inset ${{ ok: 'bg-emerald-50 text-emerald-700 ring-emerald-200', reorder: 'bg-gold-50 text-gold-700 ring-gold-200', critical: 'bg-red-50 text-red-700 ring-red-200', degrading: 'bg-orange-50 text-orange-700 ring-orange-200' }[ftone]}`}>{friendly}</span>
      </div>
      <p className="mt-2 text-base text-slate-600">{cover}.{s.status === 'degrading' && ` It keeps for about ${days(s.degrades_in_days, 0)} more days.`}</p>
      <LevelBar s={s} />
      {editable && s.status !== 'ok' && (
        <button onClick={fix} disabled={fixing} className="mt-4 w-full rounded-xl bg-brand-600 px-4 py-3.5 text-base font-semibold text-white active:bg-brand-700 disabled:opacity-60">
          {fixing ? 'Ariadne is working…' : s.is_finished ? 'Ask Ariadne to check my buyers now' : 'Ask Ariadne to restock now'}</button>)}
      {msg && <p className="mt-2 text-sm text-red-600">{msg}</p>}
      <button onClick={() => setDetails(d => !d)} className="mt-3 block text-sm text-slate-500 underline-offset-2 hover:underline">{details ? 'Hide details' : 'Details'}</button>
      {details && <div className="mt-2 grid grid-cols-2 gap-1 text-sm text-slate-500">
        <div>Safety stock <b className="text-slate-700">{kg(s.safety_stock)} kg</b></div><div>Reorder point <b className="text-slate-700">{kg(s.reorder_point)} kg</b></div>
        <div>Sellable <b className="text-slate-700">{s.is_finished ? kg(s.sellable) + ' kg' : '—'}</b></div><div>Reserved <b className="text-slate-700">{kg(s.reserved)} kg</b></div>
        <div>Daily use <b className="text-slate-700">{kg(s.daily_demand, 1)} kg</b></div><div>Price <b className="text-slate-700">₹{kg(s.unit_price)}/kg</b></div></div>}
      {form}
    </div>)
  return (
    <div className="rounded-xl border border-brand-100/80 bg-white p-4">
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
          {fixing ? 'Ariadne is working…' : s.is_finished ? 'Ask Ariadne to check my buyers now' : 'Ask Ariadne to restock now'}</button>
      )}
      {form}
    </div>
  )
}
