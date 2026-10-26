import { Link } from 'react-router-dom'
import { Badge, btn, inr } from './ui'
import RouteView from './RouteView'

const STATUS: Record<string, [string, string]> = {
  pending: ['reorder', 'Waiting for approvals'], approved: ['blue', 'Both approved'], executed: ['ok', 'Completed'],
  rejected: ['critical', 'Declined'], failed_funds: ['critical', 'Failed: insufficient funds/stock'],
}
const DEC: Record<string, [string, string]> = { approved: ['ok', 'approved'], pending: ['reorder', 'not decided yet'], rejected: ['critical', 'declined'] }

function Side({ role, name, dec }: { role: string; name: string; dec: string }) {
  const [tone, word] = DEC[dec] ?? DEC.pending
  return <div className="flex items-center gap-2 text-xs"><span className="text-slate-400">{role}</span><span className="font-medium text-slate-700">{name}</span><Badge tone={tone}>{word}</Badge></div>
}

function dealTitle(d: any) {
  const kgText = `${Number(d.quantity).toLocaleString('en-IN', { maximumFractionDigits: 0 })} kg ${d.product}`
  if (d.my_side === 'seller') return <>Sell {kgText} to <b>{d.buyer.name}</b></>
  if (d.my_side === 'buyer') return <>Buy {kgText} from <b>{d.seller.name}</b></>
  return <><b>{d.seller.name}</b> sells {kgText} to <b>{d.buyer.name}</b></>
}

/** One sentence on where the deal stands from the viewer's point of view. */
function standing(d: any): { tone: string; text: string } | null {
  const declinedBy = d.seller_decision === 'rejected' ? d.seller.name : d.buyer_decision === 'rejected' ? d.buyer.name : null
  if (d.status === 'rejected') return { tone: 'text-red-700', text: `Declined${declinedBy ? ` by ${declinedBy}` : ''}. Nothing changed; Ariadne looks for another option.` }
  if (d.status === 'executed') return { tone: 'text-emerald-700', text: 'Completed. Stock and money have moved.' }
  if (d.status === 'approved') return { tone: 'text-sky-700', text: 'Both sides approved. It completes as soon as the other offers in the same request are decided.' }
  if (d.status !== 'pending') return null
  const mine = d.my_side === 'seller' ? d.seller_decision : d.my_side === 'buyer' ? d.buyer_decision : null
  const other = d.my_side === 'seller' ? d.buyer : d.seller
  const otherDec = d.my_side === 'seller' ? d.buyer_decision : d.seller_decision
  if (mine === 'approved') return { tone: 'text-gold-700', text: `You approved. Waiting for ${other.name} to approve. Nothing moves until both of you say yes.` }
  if (mine === 'pending' && otherDec === 'approved') return { tone: 'text-emerald-700', text: `${other.name} already approved. It is your turn.` }
  if (mine === 'pending') return { tone: 'text-slate-500', text: `Needs your yes or no. ${other.name} also has to approve before anything moves.` }
  return { tone: 'text-gold-700', text: 'Waiting for the seller and the buyer to approve. Nothing moves until both say yes.' }
}

export default function DealCard({ d, onDecide, busy, big }: { d: any; onDecide?: (id: number, approve: boolean) => void; busy?: boolean; big?: boolean }) {
  const [tone, label] = STATUS[d.status] ?? ['slate', d.status]
  const st = standing(d)
  return (
    <div className="rounded-2xl border border-brand-100/80 bg-white p-5">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className={`${big ? 'text-lg' : 'text-[15px]'} font-semibold text-ink`}>{dealTitle(d)} for {inr(d.total)}</div>
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
      <div className="mt-3 space-y-1"><Side role="Seller" name={d.seller.name} dec={d.seller_decision} /><Side role="Buyer" name={d.buyer.name} dec={d.buyer_decision} /></div>
      {d.note && <p className="mt-3 text-sm text-slate-500">{d.note}</p>}
      {st && <p className={`mt-2 text-sm font-medium ${st.tone}`}>{st.text}</p>}
      {d.route?.routes?.length > 0 && <details className="mt-3"><summary className="text-xs font-medium text-brand-600">Show route</summary><div className="mt-2"><RouteView route={d.route} /></div></details>}
      {d.can_decide && onDecide && (
        <div className="mt-4 flex gap-3">
          <button disabled={busy} onClick={() => onDecide(d.id, true)} className={`${btn.good} ${big ? 'flex-1 py-3.5 text-base' : ''}`}>{d.my_side === 'seller' ? 'Yes, I will sell' : 'Yes, buy this'}</button>
          <button disabled={busy} onClick={() => onDecide(d.id, false)} className={`${btn.bad} ${big ? 'flex-1 py-3.5 text-base' : ''}`}>No, decline</button>
        </div>)}
    </div>
  )
}
