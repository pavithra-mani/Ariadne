import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, post } from '../api'
import { useAuth } from '../auth'
import StockCard from '../components/StockCard'
import TargetCard from '../components/TargetCard'
import { Badge, Card, PageHeader, Stat, btn, inr, kg } from '../components/ui'
import { FRIENDLY_STATUS, KIND_LABEL, isFarmer, type Dashboard as D, type EntityView } from '../types'

const LEVEL_STYLE: Record<string, string> = {
  alert: 'border-red-200 bg-red-50', warning: 'border-gold-200 bg-gold-50', deal: 'border-emerald-200 bg-emerald-50', info: 'border-slate-200 bg-slate-50',
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
    <details className="group rounded-xl border border-brand-100/80 bg-white">
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

function SimpleOutlook({ o, onFixed }: { o: any; onFixed: (r: any, p: string) => void }) {
  const risky = o.status === 'at_risk'
  return (
    <div className={`mb-6 rounded-2xl border p-5 ${risky ? 'border-red-200 bg-red-50' : 'border-emerald-200 bg-emerald-50'}`}>
      <div className="text-lg font-semibold text-ink">{risky ? `Your ${o.product} supply may fall short` : `Your ${o.product} supply looks fine`}</div>
      <p className="mt-1 text-base text-slate-600">{risky
        ? `About ${kg(o.expected_loss)} kg of ${o.product} may not arrive from your suppliers. Ariadne is looking for other sources.`
        : `Your suppliers can send what you need over the next ${o.horizon_days} days.`}</p>
      <details className="mt-3"><summary className="text-sm text-slate-500 underline-offset-2 hover:underline">Details</summary><div className="mt-3"><Outlook o={o} onFixed={onFixed} /></div></details>
    </div>
  )
}

export default function Dashboard() {
  const { user } = useAuth()
  const [d, setD] = useState<D | null>(null)
  const [notes, setNotes] = useState<any[]>([])
  const [err, setErr] = useState('')
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
  const farmer = isFarmer(user?.role)
  const sup = partners.filter(p => p.relation === 'supplier'), buy = partners.filter(p => p.relation === 'buyer')
  const others = partners.filter(p => p.relation === 'network')
  const attention = notes.filter(n => !n.read && n.level !== 'deal').slice(0, 3)
  const wh = me.warehouse
  const low = me.stock.filter(s => s.status !== 'ok')

  const bannerEl = banner && (() => {
    const nBuyers = Math.max(banner.r.buyer_incidents_list?.length ?? 0, typeof banner.r.buyer_incidents === 'number' ? banner.r.buyer_incidents : 0)
    return (
      <div className="mb-6 space-y-2 rounded-xl border border-brand-100 bg-brand-50 p-4 text-sm text-brand-700">
        {banner.r.incident_id && (
          <div><b>Ariadne {banner.r.existing ? 'is already handling' : 'opened incident'} #{banner.r.incident_id}</b> for your {banner.product} stock.{' '}
            {banner.r.pending_deals > 0
              ? <>It found suppliers and routes and sent offers: <Link to="/approvals" className="font-semibold underline">review {banner.r.pending_deals} deal{banner.r.pending_deals === 1 ? '' : 's'}</Link>. Nothing moves until the seller and you both approve.</>
              : <>Status: {String(banner.r.status).replace(/_/g, ' ')}. <Link to="/incidents" className="font-semibold underline">See the details</Link>.</>}</div>)}
        {nBuyers > 0 && <div><b>Your buyers were protected too:</b> Ariadne opened {nBuyers} incident{nBuyers === 1 ? '' : 's'} for buyers this change leaves short, and offers are on their way.</div>}
      </div>)
  })()
  const attentionEl = attention.length > 0 && (
    <div className="mb-6 space-y-2">
      {attention.map(n => (
        <div key={n.id} className={`flex items-start gap-3 rounded-xl border p-3.5 ${farmer ? 'text-base' : 'text-sm'} ${LEVEL_STYLE[n.level] ?? LEVEL_STYLE.info}`}>
          <span className="mt-0.5 text-slate-500">⚠</span><div className="flex-1 text-slate-700">{n.message}</div>
        </div>))}
      <Link to="/alerts" className="text-sm font-medium text-brand-600 hover:underline">View all alerts →</Link>
    </div>)

  if (farmer) return (
    <div>
      <PageHeader title={`Hello, ${me.owner_name.split(' ')[0]}`} subtitle={`${me.name} · ${me.village}. Here is how your stock is and what needs doing.`} />
      <div className={`mb-6 rounded-2xl border p-5 ${low.length ? 'border-gold-200 bg-gold-50' : 'border-emerald-200 bg-emerald-50'}`}>
        <div className="text-lg font-semibold text-ink">{low.length ? `${low.length === 1 ? 'One thing needs' : `${low.length} things need`} your attention` : 'Everything looks good'}</div>
        <p className="mt-1 text-base text-slate-600">{low.length ? low.map(s => `${s.product}: ${FRIENDLY_STATUS[s.status][0].toLowerCase()}`).join(' · ') : 'Your stock is fine and Ariadne is watching your suppliers and buyers for you.'}</p>
        <div className="mt-4 flex flex-wrap gap-3">
          <Link to="/assistant" className={`${btn.primary} px-5 py-3 text-base`}>Report a problem</Link>
          <Link to="/approvals" className={`${btn.ghost} px-5 py-3 text-base`}>See offers</Link>
        </div>
      </div>
      {attentionEl}{bannerEl}
      {me.outlook?.map((o: any) => <SimpleOutlook key={o.product} o={o} onFixed={showResult} />)}
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">My stock</h2>
      <div className="mb-8 grid gap-4 md:grid-cols-2">{me.stock.map(s => <StockCard key={s.product} s={s} simple editable onSaved={load} onIncident={showResult} />)}</div>
      <div className="mb-4 grid grid-cols-2 gap-3">
        <div className="rounded-2xl border border-brand-100/80 bg-white p-4"><div className="text-sm text-slate-500">My money</div><div className="text-xl font-semibold text-ink">{inr(me.balance)}</div></div>
        <div className="rounded-2xl border border-brand-100/80 bg-white p-4"><div className="text-sm text-slate-500">Who I sell to / buy from</div><div className="text-xl font-semibold text-ink">{buy.length} / {sup.length}</div></div>
      </div>
      <Network sup={sup} buy={buy} others={others} simple />
    </div>
  )

  return (
    <div>
      <PageHeader title={me.name} subtitle={`${me.village} · ${me.owner_name} · ${KIND_LABEL[me.kind]}. Your stock, your suppliers and buyers, and what needs attention.`} />
      <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Money balance" value={inr(me.balance)} />
        <Stat label="Capacity in use" value={`${Math.round(me.capacity.utilisation * 100)}%`} bar={me.capacity.utilisation}
          tone={me.capacity.utilisation > 0.9 ? 'red' : 'brand'} sub={`${me.capacity.load} of ${me.capacity.capacity} kg/day · ${me.capacity.spare} spare`} />
        {wh ? <Stat label={`Warehouse (${wh.stores})`} value={`${Math.round(wh.utilisation * 100)}%`} bar={wh.utilisation} tone={wh.utilisation > 0.85 ? 'amber' : 'brand'} sub={`${wh.used} of ${wh.capacity} kg stored`} />
          : <Stat label="Produce kept" value="On the farm" sub="Farmers store before dispatch" />}
        <Stat label="Stock alerts" value={d.summary.alerts.length} tone="red" sub={d.summary.alerts.join(' · ') || 'All stock healthy'} />
      </div>
      {attentionEl}{bannerEl}
      {(user?.role === 'reeler' || user?.role === 'spinner') && <TargetCard role={user.role} onDone={load} />}
      {me.outlook?.map((o: any) => <Outlook key={o.product} o={o} onFixed={showResult} />)}
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">My stock</h2>
      <div className="mb-8 grid gap-4 md:grid-cols-2">{me.stock.map(s => <StockCard key={s.product} s={s} editable onSaved={load} onIncident={showResult} />)}</div>
      {wh && (
        <Card className="mb-8" title={wh.name} subtitle={`${wh.village} · holds your finished ${wh.stores}. Pick-ups for rerouted deals start here.`}>
          <div className="h-2 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-brand-500" style={{ width: `${Math.min(wh.utilisation * 100, 100)}%` }} /></div>
          <div className="mt-2 text-xs text-slate-500">{wh.used} of {wh.capacity} kg · {sup.length} supplier{sup.length === 1 ? '' : 's'} deliver to it</div>
        </Card>
      )}
      <Network sup={sup} buy={buy} others={others} />
    </div>
  )
}

function Network({ sup, buy, others, simple }: { sup: EntityView[]; buy: EntityView[]; others: EntityView[]; simple?: boolean }) {
  const [more, setMore] = useState(false)
  const section = (title: string, rows: EntityView[], empty: string) => (
    <div className="mb-6"><h3 className="mb-2 text-sm font-semibold text-ink">{title} <span className="font-normal text-slate-400">({rows.length})</span></h3>
      <div className="space-y-2">{rows.map(p => <Partner key={p.id} p={p} />)}{rows.length === 0 && <p className="text-sm text-slate-400">{empty}</p>}</div></div>)
  return (
    <>
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-400">{simple ? 'People I deal with' : 'My network'}</h2>
      {section('Your suppliers', sup, 'No suppliers linked yet.')}
      {section('Your buyers', buy, 'No buyers linked yet.')}
      {others.length > 0 && (
        <div className="mb-4">
          <button onClick={() => setMore(m => !m)} className="mb-2 text-sm font-medium text-brand-600 hover:underline">{more ? 'Hide' : 'Show'} everyone else in the chain ({others.length})</button>
          {more && <div className="space-y-2">{others.map(p => <Partner key={p.id} p={p} />)}</div>}
        </div>)}
    </>
  )
}
