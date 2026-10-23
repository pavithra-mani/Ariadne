import { Link } from 'react-router-dom'
import { Badge, btn, inr } from './ui'
import RouteView from './RouteView'

const STATUS: Record<string, [string, string]> = {
  pending: ['reorder', 'Awaiting approval'], approved: ['blue', 'Approved'], executed: ['ok', 'Completed'],
  rejected: ['critical', 'Rejected'], failed_funds: ['critical', 'Failed: insufficient funds/stock'],
}

export default function DealCard({ d, onDecide, busy }: { d: any; onDecide?: (id: number, approve: boolean) => void; busy?: boolean }) {
  const [tone, label] = STATUS[d.status] ?? ['slate', d.status]
  return (
    <div className="rounded-2xl border border-slate-200/70 bg-white p-5">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="text-[15px] font-semibold text-ink">{d.seller.name} <span className="text-slate-300">→</span> {d.buyer.name}</div>
          <div className="mt-0.5 text-xs text-slate-500">Deal #{d.id} · {d.deal_type.replace('_', '–')}{d.incident_id && <> · from <Link className="text-brand-600 hover:underline" to="/incidents">incident #{d.incident_id}</Link></>}</div>
        </div>
        <Badge tone={tone}>{label}</Badge>
      </div>
      <div className="mt-4 grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
        <div><div className="text-xs text-slate-400">Product</div><div className="font-medium capitalize text-ink">{d.product}</div></div>
        <div><div className="text-xs text-slate-400">Quantity</div><div className="font-medium text-ink">{d.quantity} kg</div></div>
        <div><div className="text-xs text-slate-400">Price</div><div className="font-medium text-ink">{inr(d.unit_price)}/kg</div></div>
        <div><div className="text-xs text-slate-400">Total incl. transport</div><div className="font-medium text-ink">{inr(d.total)}</div></div>
      </div>
      {d.note && <p className="mt-3 text-sm text-slate-500">{d.note}</p>}
      {d.status === 'pending' && !d.can_decide && d.approver && <p className="mt-2 text-xs font-medium text-amber-700">Waiting for {d.approver.name} to approve. No stock or balance changes until then.</p>}
      {d.route?.routes?.length > 0 && <details className="mt-3"><summary className="text-xs font-medium text-brand-600">Show route</summary><div className="mt-2"><RouteView route={d.route} /></div></details>}
      {d.can_decide && onDecide && (
        <div className="mt-4 flex gap-2">
          <button disabled={busy} onClick={() => onDecide(d.id, true)} className={btn.good}>Approve</button>
          <button disabled={busy} onClick={() => onDecide(d.id, false)} className={btn.bad}>Reject</button>
        </div>)}
    </div>
  )
}
