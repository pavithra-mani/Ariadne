import { useEffect, useState } from 'react'
import { api, post } from '../api'
import { Badge, Card, Icon, PageHeader, btn, input, kg } from '../components/ui'
import { KIND_LABEL } from '../types'

interface Tier { kind: string; n: number; in_product: string | null; out_product: string; requested_out: number; feasible_out: number; need_in: number; short_linked: number; short_final: number; n_short: number }
interface Flow { horizon_days: number; tiers: Tier[]; entities: any[]; gaps: any[]; rounds: { round: number; short_kg: number; spilled_kg: number }[]; ok: boolean; converged: boolean }

const ORDER = ['mulberry_farm', 'silkworm_farm', 'reeler', 'spinner']  // the way product flows
const REASON: Record<string, string> = {
  stock_changed: 'A stock change', target_set: 'A new demand target', deal_executed: 'A deal was completed', deal_rejected: 'A deal was declined',
  incident: 'A problem was reported', startup: 'The service restarted',
}
const asked = (t: Tier) => (t.kind === 'spinner' ? t.need_in : t.requested_out)

/** One tier as a box: how much it is asked for, how much can be delivered, what is short. */
function TierBox({ t, compare, horizon }: { t: Tier; compare?: Tier; horizon: number }) {
  const want = asked(t)
  const short = t.short_final
  const rerouted = Math.max(t.short_linked - t.short_final, 0)
  const ok = Math.max(want - short, 0)
  const pct = (x: number) => `${want > 0 ? Math.min((x / want) * 100, 100) : 0}%`
  const delta = compare ? asked(t) - asked(compare) : 0
  return (
    <div className={`flex-1 rounded-2xl border p-4 ${short > 0.5 ? 'border-red-200 bg-red-50/50' : rerouted > 0.5 ? 'border-gold-200 bg-gold-50/50' : 'border-brand-100/80 bg-white'}`}>
      <div className="flex items-start justify-between gap-2">
        <div><div className="text-sm font-semibold text-ink">{KIND_LABEL[t.kind]}s</div><div className="text-xs text-slate-400">{t.n} in the chain</div></div>
        {short > 0.5 ? <Badge tone="critical">{t.n_short} short</Badge> : rerouted > 0.5 ? <Badge tone="reorder">rerouted</Badge> : <Badge tone="ok">balanced</Badge>}
      </div>
      <div className="mt-3 text-xs text-slate-500">{t.kind === 'spinner' ? `Wants ${t.in_product}` : `Asked for ${t.out_product}`} over the next {horizon} days</div>
      <div className="text-xl font-semibold text-ink">{kg(want)} <span className="text-sm font-normal text-slate-400">kg</span>
        {compare && Math.abs(delta) > 0.5 && <span className={`ml-2 text-xs font-medium ${delta > 0 ? 'text-red-600' : 'text-emerald-600'}`}>{delta > 0 ? '+' : ''}{kg(delta)}</span>}</div>
      <div className="mt-2 flex h-2.5 overflow-hidden rounded-full bg-slate-100">
        <div className="bg-emerald-500" style={{ width: pct(ok - rerouted) }} /><div className="bg-amber-400" style={{ width: pct(rerouted) }} /><div className="bg-red-500" style={{ width: pct(short) }} />
      </div>
      <div className="mt-2 space-y-0.5 text-xs text-slate-500">
        <div><span className="mr-1 inline-block h-2 w-2 rounded-full bg-emerald-500" />{kg(Math.max(ok - rerouted, 0))} kg from current suppliers</div>
        {rerouted > 0.5 && <div><span className="mr-1 inline-block h-2 w-2 rounded-full bg-amber-400" />{kg(rerouted)} kg covered by other suppliers</div>}
        {short > 0.5 && <div className="font-medium text-red-600"><span className="mr-1 inline-block h-2 w-2 rounded-full bg-red-500" />{kg(short)} kg still short</div>}
      </div>
    </div>
  )
}

function TierRow({ tiers, compare, horizon }: { tiers: Tier[]; compare?: Tier[]; horizon: number }) {
  const by = (ts: Tier[]) => Object.fromEntries(ts.map(t => [t.kind, t]))
  const b = by(tiers), c = compare ? by(compare) : {}
  return (
    <div className="flex flex-col items-stretch gap-2 lg:flex-row lg:items-stretch">
      {ORDER.map((k, i) => (
        <div key={k} className="flex flex-1 flex-col items-stretch gap-2 lg:flex-row lg:items-stretch">
          <TierBox t={b[k]} compare={c[k]} horizon={horizon} />
          {i < ORDER.length - 1 && <div className="flex items-center justify-center text-slate-300"><span className="rotate-90 text-xl lg:rotate-0">→</span></div>}
        </div>))}
    </div>
  )
}

function Rounds({ f }: { f: Flow }) {
  const n = f.rounds.length
  const spilled = f.rounds.reduce((a, r) => a + r.spilled_kg, 0)
  return (
    <p className="mt-3 text-sm text-slate-600">
      {spilled > 0 ? <>Ariadne re-asked other suppliers <b>{Math.max(n - 1, 1)} time{n - 1 === 1 ? '' : 's'}</b> ({kg(spilled)} kg moved) {f.converged ? 'until the numbers settled.' : 'but they had not fully settled yet.'}</>
        : <>Current suppliers can cover this on their own; no rerouting was needed.</>}
    </p>
  )
}

export default function Chain() {
  const [f, setF] = useState<Flow | null>(null)
  const [act, setAct] = useState<any[]>([])
  const [ent, setEnt] = useState('')
  const [qty, setQty] = useState('')
  const [sim, setSim] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const load = () => { api('/api/flow').then(setF); api('/api/agent/activity').then(setAct) }
  useEffect(() => { load(); const t = setInterval(() => api('/api/agent/activity').then(setAct).catch(() => {}), 6000); return () => clearInterval(t) }, [])
  if (!f) return <p className="text-slate-500">Loading…</p>
  const buyers = f.entities.filter(e => e.kind === 'spinner' || e.kind === 'reeler')
  const run = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!ent || !qty) return
    setBusy(true); setErr('')
    try { setSim(await post('/api/flow/what-if', { entity_id: Number(ent), qty: Number(qty) })) } catch (x: any) { setErr(x.message) } finally { setBusy(false) }
  }
  const entity = (id: number) => f.entities.find(e => e.id === id)
  return (
    <div>
      <PageHeader title="The whole chain" subtitle="Mulberry farms, silkworm farms, reelers and spinners in one view: what each tier is asked for, what it can deliver, and what Ariadne did about it." />
      <div className={`mb-4 flex items-center gap-3 rounded-xl border p-3.5 text-sm ${f.ok && f.gaps.length === 0 ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : f.ok ? 'border-gold-200 bg-gold-50 text-gold-700' : 'border-red-200 bg-red-50 text-red-800'}`}>
        <Icon name="chain" className="h-5 w-5" />
        {f.ok && f.gaps.length === 0 ? `Every tier can meet demand over the next ${f.horizon_days} days.`
          : f.ok ? `${f.gaps.length} partner${f.gaps.length === 1 ? '' : 's'} cannot be served by current suppliers, but other suppliers can cover it. Ariadne is arranging offers.`
          : 'Demand is higher than the chain can supply. Ariadne is arranging offers where it can; the rest is shown in red.'}
      </div>
      <Card title="Supply chain, left to right" subtitle="Green: delivered by current suppliers. Amber: other suppliers have to step in. Red: still short.">
        <TierRow tiers={f.tiers} horizon={f.horizon_days} />
        <Rounds f={f} />
      </Card>

      {f.gaps.length > 0 && (
        <Card className="mt-4" title="Who is short right now" pad={false}>
          <ul className="divide-y divide-slate-100">{f.gaps.slice(0, 8).map(g => (
            <li key={g.entity_id} className="flex flex-wrap items-center justify-between gap-2 px-5 py-3 text-sm">
              <span><b className="text-ink">{g.name}</b> <span className="text-slate-400">· {KIND_LABEL[g.kind]}</span></span>
              <span className="text-slate-600">needs {kg(g.short_linked)} kg more {g.product}{g.short_final > 0.5 ? <span className="text-red-600"> · {kg(g.short_final)} kg unmet</span> : ' · covered by other suppliers'}</span>
            </li>))}</ul>
        </Card>)}

      <Card className="mt-4" title="What if demand grows?" subtitle="Pick a reeler or spinner and add demand. Nothing is saved and nobody is notified; this only shows what would happen.">
        <form onSubmit={run} className="flex flex-wrap items-center gap-2">
          <select className={`${input} min-w-48`} value={ent} onChange={e => setEnt(e.target.value)}>
            <option value="">Choose who gets more demand…</option>
            {buyers.map(e => <option key={e.id} value={e.id}>{e.name} ({KIND_LABEL[e.kind]})</option>)}</select>
          <input className={`${input} w-40`} type="number" min={1} placeholder="extra kg yarn" value={qty} onChange={e => setQty(e.target.value)} />
          <button disabled={busy || !ent || !qty} className={btn.primary}>{busy ? 'Working it out…' : 'Show me'}</button>
        </form>
        {err && <p className="mt-2 text-sm text-red-600">{err}</p>}
        {sim && (
          <div className="mt-5 space-y-4">
            <div className="text-sm text-slate-600">If <b>{sim.entity.name}</b> gets <b>{kg(sim.qty)} kg</b> more demand:</div>
            <div><div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">Before</div><TierRow tiers={sim.before.tiers} horizon={sim.before.horizon_days} /></div>
            <div><div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">After</div><TierRow tiers={sim.after.tiers} compare={sim.before.tiers} horizon={sim.after.horizon_days} /><Rounds f={sim.after} /></div>
            {sim.after.gaps.length > 0 && <p className="text-sm text-slate-500">{sim.after.gaps.length} partner(s) would need new suppliers, for example {sim.after.gaps.slice(0, 3).map((g: any) => `${g.name} (${kg(g.short_linked)} kg ${g.product})`).join(', ')}.</p>}
            <p className="text-xs text-slate-400">To make this real, set the demand on your Dashboard: Ariadne then does this check itself and sends the offers.</p>
          </div>)}
      </Card>

      <Card className="mt-4" title="What Ariadne did automatically" subtitle="Every change wakes the agent. It checks the whole chain and opens incidents and offers by itself; nobody has to press a button." pad={false}>
        {act.length === 0 ? <p className="p-5 text-sm text-slate-500">Nothing yet. Change a stock level or add demand and it shows up here.</p> : (
          <ul className="divide-y divide-slate-100">{act.slice(0, 12).map(a => {
            const agent = a.mode === 'agent' || a.mode === 'agent+rules'
            const nOffers = (a.offers?.length ?? 0) + (a.opened?.length ?? 0)
            return (
            <li key={a.id} className="px-5 py-3 text-sm">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div><div className="font-medium text-ink">{REASON[a.reason] ?? a.reason}{a.entity && <span className="font-normal text-slate-500"> · {a.entity}{a.product ? ` (${a.product})` : ''}</span>}</div>
                  <div className="mt-0.5 text-slate-500">{a.status === 'error' ? `Error: ${a.error}` : a.status !== 'done' ? 'Working on it…'
                    : a.summary ? a.summary
                    : a.opened?.length ? `Opened ${a.opened.length} incident${a.opened.length === 1 ? '' : 's'} and sent offers: ${[...new Set(a.opened.map((o: any) => entity(o.entity_id)?.name ?? `#${o.entity_id}`))].slice(0, 4).join(', ')}${a.opened.length > 4 ? '…' : ''}`
                    : 'Checked the chain: nothing needed doing.'}</div></div>
                <div className="text-right text-xs text-slate-400">
                  {a.mode && <Badge tone={a.mode === 'agent' ? 'ok' : 'reorder'}>{a.mode === 'agent' ? 'AI agent decided' : a.mode === 'agent+rules' ? 'AI agent, then rules' : 'rules (AI unavailable)'}</Badge>}
                  <div className="mt-1">{new Date(a.created_at).toLocaleTimeString()}</div></div>
              </div>
              {a.fallback_reason && <p className="mt-1 text-xs text-gold-700">Fell back to fixed rules: {String(a.fallback_reason).slice(0, 140)}</p>}
              {agent && a.steps?.length > 0 && (
                <details className="mt-1 text-xs text-slate-500">
                  <summary className="cursor-pointer">{a.steps.length} steps the agent chose · {a.offers?.length ?? 0} offer(s) sent{a.residual?.length ? ` · ${a.residual.length} shortfall(s) still open` : ''}{a.invalid_tool_calls ? ` · ${a.invalid_tool_calls} refused by safety checks` : ''}</summary>
                  <ol className="mt-1 list-decimal space-y-0.5 pl-5">{a.steps.map((st: any, i: number) => (
                    <li key={i}><b>{st.tool}</b> <span className="text-slate-400">{JSON.stringify(st.args).slice(0, 110)}</span>{st.result?.error && <span className="text-red-600"> → refused: {st.result.error}</span>}</li>))}</ol>
                </details>)}
              {nOffers === 0 && a.status === 'done' && !a.summary && null}
            </li>)})}</ul>)}
      </Card>
    </div>
  )
}
