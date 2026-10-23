import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, post } from '../api'
import { useAuth } from '../auth'
import StockCard from '../components/StockCard'
import { Badge, Card, Empty, PageHeader, Stat, Tabs, btn, inr, kg } from '../components/ui'
import { KIND_LABEL, type Dashboard as D, type EntityView } from '../types'

const LEVEL_STYLE: Record<string, string> = {
  alert: 'border-red-200 bg-red-50', warning: 'border-amber-200 bg-amber-50', deal: 'border-emerald-200 bg-emerald-50', info: 'border-slate-200 bg-slate-50',
}

function Outlook({ o, onFixed }: { o: any; onFixed: (r: any, p: string) => void }) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const risky = o.status === 'at_risk'
  const go = async () => {
    setBusy(true); setErr('')
    try { onFixed(await post(`/api/stock/${o.product}/replenish`), o.product) } catch (e: any) { setErr(e.message) } finally { setBusy(false) }
  }
  return (
    <Card className="mb-8" title={`Supply outlook · ${o.product}`}
      subtitle={`What your suppliers can ship against the ${kg(o.need)} kg you use in ${o.horizon_days} days. Updates the moment a supplier reports a problem or changes its stock.`}
      right={risky ? <Badge tone="critical">below reorder point</Badge> : o.expected_loss > 0 ? <Badge tone="reorder">covered by your stock</Badge> : <Badge tone="ok">on track</Badge>}>
      <div className="grid gap-4 text-sm sm:grid-cols-4">
        <div><div className="text-xs text-slate-400">On hand</div><div className="text-lg font-semibold text-ink">{kg(o.available)} kg</div></div>
        <div><div className="text-xs text-slate-400">Expected not to arrive</div><div className={`text-lg font-semibold ${o.expected_loss > 0 ? 'text-red-600' : 'text-ink'}`}>{kg(o.expected_loss)} kg</div></div>
        <div><div className="text-xs text-slate-400">Projected stock</div><div className={`text-lg font-semibold ${risky ? 'text-red-600' : 'text-ink'}`}>{kg(o.projected)} kg</div></div>
        <div><div className="text-xs text-slate-400">Reorder point</div><div className="text-lg font-semibold text-ink">{kg(o.reorder_point)} kg</div></div>
      </div>
      <div className="mt-4 overflow-hidden rounded-xl border border-slate-100">
        {o.suppliers.map((s: any) => (
          <div key={s.entity_id} className="flex items-center justify-between gap-3 border-b border-slate-100 px-4 py-2.5 text-sm last:border-0">
            <div><span className="font-medium text-ink">{s.name}</span> <span className="text-slate-400">· {s.village} · {Math.round(s.share * 100)}% of your supply</span></div>
            <div className="flex items-center gap-2">
              <span className="text-slate-500">can ship {kg(s.covered)} of {kg(s.want)} kg · {kg(s.sellable)} sellable</span>
              {s.loss_pct > 0 ? <Badge tone="critical">{s.loss_pct}% output hit · −{kg(s.at_stake)} kg to you</Badge> : s.at_stake > 0 ? <Badge tone="critical">short {kg(s.at_stake)} kg</Badge> : <Badge tone="ok">on track</Badge>}
            </div>
          </div>))}
      </div>
      {risky && (
        <div className="mt-4 flex items-center gap-3">
          <button onClick={go} disabled={busy} className={btn.primary}>{busy ? 'Ariadne is working…' : `Find alternatives for ≈${kg(o.gap)} kg`}</button>
          {err && <span className="text-sm text-red-600">{err}</span>}
        </div>)}
    </Card>
  )
}

function Partner({ p }: { p: EntityView }) {
  const bad = p.stock.filter(s => s.status !== 'ok')
  return (
    <details className="group rounded-xl border border-slate-200/80 bg-white">
      <summary className="flex flex-wrap items-center gap-3 px-4 py-3">
        <div className="min-w-0 flex-1">
          <div className="font-medium text-ink">{p.name}</div>
          <div className="text-xs text-slate-500">{KIND_LABEL[p.kind]} · {p.village} · {p.owner_name}</div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {bad.length === 0 ? <Badge tone="ok">stock ok</Badge> : bad.map(s => <Badge key={s.product} tone={s.status}>{s.product}: {s.status}</Badge>)}
          <span className="text-sm text-slate-500">{inr(p.balance)}</span>
          <span className="text-slate-300 transition group-open:rotate-90">›</span>
        </div>
      </summary>
      <div className="grid gap-3 border-t border-slate-100 p-4 md:grid-cols-2">{p.stock.map(s => <StockCard key={s.product} s={s} compact />)}</div>
    </details>
  )
}

export default function Dashboard() {
  const { user } = useAuth()
  const [d, setD] = useState<D | null>(null)
  const [notes, setNotes] = useState<any[]>([])
  const [err, setErr] = useState('')
  const [tab, setTab] = useState('buyers')
  const [banner, setBanner] = useState<{ r: any; product: string } | null>(null)
  const showResult = (r: any, product: string) => { setBanner({ r, product }); load() }
  const load = () => {
    api<D>('/api/dashboard').then(setD).catch(e => setErr(e.message))
    api('/api/notifications').then(setNotes).catch(() => {})
  }
  useEffect(() => { load() }, [])
  if (err) return <p className="text-red-600">{err}</p>
  if (!d) return <p className="text-slate-500">Loading…</p>
  const { me, partners } = d
  const sup = partners.filter(p => p.relation === 'supplier'), buy = partners.filter(p => p.relation === 'buyer')
  const attention = notes.filter(n => !n.read && n.level !== 'deal').slice(0, 3)
  const wh = me.warehouse

  return (
    <div>
      <PageHeader title={me.name} subtitle={`${me.village} · ${me.owner_name} · ${user ? '' : ''}${KIND_LABEL[me.kind]}`} />
      <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Money balance" value={inr(me.balance)} />
        <Stat label="Capacity in use" value={`${Math.round(me.capacity.utilisation * 100)}%`} bar={me.capacity.utilisation}
          tone={me.capacity.utilisation > 0.9 ? 'red' : 'brand'} sub={`${me.capacity.load} of ${me.capacity.capacity} kg/day · ${me.capacity.spare} spare`} />
        {wh ? <Stat label={`Warehouse (${wh.stores})`} value={`${Math.round(wh.utilisation * 100)}%`} bar={wh.utilisation} tone={wh.utilisation > 0.85 ? 'amber' : 'brand'} sub={`${wh.used} of ${wh.capacity} kg stored`} />
          : <Stat label="Produce kept" value="On the farm" sub="Farmers store before dispatch" />}
        <Stat label="Stock alerts" value={d.summary.alerts.length} tone="red" sub={d.summary.alerts.join(' · ') || 'All stock healthy'} />
      </div>

      {attention.length > 0 && (
        <div className="mb-6 space-y-2">
          {attention.map(n => (
            <div key={n.id} className={`flex items-start gap-3 rounded-xl border p-3.5 text-sm ${LEVEL_STYLE[n.level] ?? LEVEL_STYLE.info}`}>
              <span className="mt-0.5 text-slate-500">⚠</span><div className="flex-1 text-slate-700">{n.message}</div>
            </div>))}
          <Link to="/alerts" className="text-xs font-medium text-brand-600 hover:underline">View all alerts →</Link>
        </div>
      )}

      {banner && (() => {
        const nBuyers = Math.max(banner.r.buyer_incidents_list?.length ?? 0, typeof banner.r.buyer_incidents === 'number' ? banner.r.buyer_incidents : 0)
        return (
        <div className="mb-6 space-y-2 rounded-xl border border-brand-100 bg-brand-50 p-4 text-sm text-brand-700">
          {banner.r.incident_id && (
            <div><b>Ariadne {banner.r.existing ? 'is already handling' : 'opened incident'} #{banner.r.incident_id}</b> for your {banner.product} stock.{' '}
              {banner.r.pending_deals > 0
                ? <>It found suppliers and routes: <Link to="/approvals" className="font-semibold underline">review {banner.r.pending_deals} proposed deal{banner.r.pending_deals === 1 ? '' : 's'} in Approvals</Link>. Nothing changes until you approve.</>
                : <>Status: {String(banner.r.status).replace(/_/g, ' ')}. <Link to="/incidents" className="font-semibold underline">See the details</Link>.</>}</div>)}
          {nBuyers > 0 ? (
            <div><b>Your buyers were protected too:</b> Ariadne opened {nBuyers} incident{nBuyers === 1 ? '' : 's'} for buyers that this change leaves short of stock. Each was alerted, alternatives were searched and routed, and the deals now wait for that buyer's approval.</div>
          ) : (banner.r.incident_id ? null : <div>No buyer is pushed below its reorder point by this change.</div>)}
        </div>
        )
      })()}
      {me.outlook?.map((o: any) => <Outlook key={o.product} o={o} onFixed={showResult} />)}
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">My stock</h2>
      <div className="mb-8 grid gap-4 md:grid-cols-2">{me.stock.map(s => <StockCard key={s.product} s={s} editable onSaved={load} onIncident={showResult} />)}</div>

      {wh && (
        <Card className="mb-8" title={wh.name} subtitle={`${wh.village} · holds your finished ${wh.stores}. Pick-ups for rerouted deals start here.`}>
          <div className="h-2 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-brand-500" style={{ width: `${Math.min(wh.utilisation * 100, 100)}%` }} /></div>
          <div className="mt-2 text-xs text-slate-500">{wh.used} of {wh.capacity} kg · {sup.length} supplier{sup.length === 1 ? '' : 's'} deliver to it</div>
        </Card>
      )}

      {partners.length > 0 ? (
        <>
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">My network</h2>
          <Tabs value={tab} onChange={setTab} tabs={[['buyers', 'Buyers', buy.length], ['suppliers', 'Suppliers', sup.length]]} />
          <div className="space-y-2">
            {(tab === 'buyers' ? buy : sup).map(p => <Partner key={p.id} p={p} />)}
            {(tab === 'buyers' ? buy : sup).length === 0 && <Card><Empty icon="home" title={`No ${tab} visible to you`} /></Card>}
          </div>
        </>
      ) : <Card><Empty icon="home" title="You can only see your own farm">Mulberry farmers see only their own data, per the data-visibility rules.</Empty></Card>}
    </div>
  )
}
