import { useEffect, useState } from 'react'
import { api, post } from '../api'
import DealCard from '../components/DealCard'
import { Card, Empty, PageHeader, Tabs, inr } from '../components/ui'

export default function Deals() {
  const [deals, setDeals] = useState<any[] | null>(null)
  const [ledger, setLedger] = useState<any[]>([])
  const [tab, setTab] = useState('active')
  const [busy, setBusy] = useState<number | null>(null)
  const load = () => { api('/api/deals').then(setDeals); api('/api/ledger').then(setLedger) }
  useEffect(() => { load() }, [])
  const decide = async (id: number, approve: boolean) => {
    setBusy(id)
    try { await post(`/api/deals/${id}/decision`, { approve }); load() } finally { setBusy(null) }
  }
  if (!deals) return <p className="text-slate-500">Loading…</p>
  const active = deals.filter(d => d.status === 'pending' || d.status === 'approved')
  const done = deals.filter(d => !['pending', 'approved'].includes(d.status))
  const list = tab === 'active' ? active : done
  return (
    <div>
      <PageHeader title="Deals & ledger" subtitle="Every offer Ariadne made, who approved or declined it, and the stock and money movements that followed." />
      <Tabs value={tab} onChange={setTab} tabs={[['active', 'In progress', active.length], ['done', 'Completed', done.length], ['ledger', 'Ledger', ledger.length]]} />
      {tab !== 'ledger' ? (
        <div className="space-y-4">
          {list.length === 0 && <Card><Empty icon="deals" title={tab === 'active' ? 'No deals in progress' : 'No completed deals yet'}>
            {tab === 'active' ? 'When an incident needs replacement supply, the proposed deals show up here until they are approved or rejected.' : 'Approved deals appear here once executed, with their ledger entries.'}</Empty></Card>}
          {list.map(d => <DealCard key={d.id} d={d} onDecide={decide} busy={busy === d.id} />)}
        </div>
      ) : (
        <Card pad={false}>
          {ledger.length === 0 ? <Empty icon="doc" title="No ledger entries yet">Stock entries and executed deals are recorded here.</Empty> : (
            <table className="w-full text-sm">
              <thead><tr className="border-b border-slate-100 text-left text-xs text-slate-400">{['When', 'Product', 'Qty (kg)', 'Money', 'Memo'].map(h => <th key={h} className="px-5 py-3 font-medium">{h}</th>)}</tr></thead>
              <tbody>{ledger.map(r => (
                <tr key={r.id} className="border-b border-slate-50 last:border-0">
                  <td className="px-5 py-3 text-slate-500">{new Date(r.created_at).toLocaleString()}</td>
                  <td className="px-5 py-3 capitalize">{r.product}</td>
                  <td className={`px-5 py-3 font-medium ${r.delta_qty < 0 ? 'text-red-600' : 'text-emerald-700'}`}>{r.delta_qty > 0 ? '+' : ''}{r.delta_qty.toFixed(1)}</td>
                  <td className={`px-5 py-3 ${r.delta_money < 0 ? 'text-red-600' : ''}`}>{r.delta_money ? inr(r.delta_money) : '—'}</td>
                  <td className="px-5 py-3 text-slate-500">{r.memo}</td></tr>))}</tbody>
            </table>)}
        </Card>
      )}
    </div>
  )
}
