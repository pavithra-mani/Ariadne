import { useEffect, useState } from 'react'
import { api, post } from '../api'
import DealCard from '../components/DealCard'
import { useAuth } from '../auth'
import { Card, Empty, PageHeader } from '../components/ui'
import { isFarmer } from '../types'

export default function Approvals() {
  const { user } = useAuth()
  const farmer = isFarmer(user?.role)
  const [waiting, setWaiting] = useState<any[]>([])
  const [rows, setRows] = useState<any[] | null>(null)
  const [busy, setBusy] = useState<number | null>(null)
  const [msg, setMsg] = useState('')
  const load = () => {
    api('/api/approvals').then(setRows)
    api('/api/deals').then((all: any[]) => setWaiting(all.filter(d => d.status === 'pending' && !d.can_decide && d.my_side)))
  }
  useEffect(() => { load() }, [])
  const decide = async (id: number, approve: boolean) => {
    setBusy(id); setMsg('')
    try {
      const r = await post(`/api/deals/${id}/decision`, { approve })
      const st = r.deal?.status
      setMsg(st === 'executed' ? 'Done: both sides approved, so stock and money have moved.'
        : st === 'rejected' ? 'You declined. Nothing changed, and Ariadne will look for another option.'
        : r.graph_resumed ? `All decisions are in. Incident #${r.incident?.id} is now ${r.incident?.status.replace(/_/g, ' ')}.`
        : 'You approved. The other side still has to approve before anything moves.')
      await load()
    } catch (e: any) { setMsg(e.message) } finally { setBusy(null) }
  }
  return (
    <div>
      <PageHeader title={farmer ? 'Offers' : 'Approvals'} subtitle="Ariadne sends offers by itself, but stock and money only move when both the seller and the buyer say yes." />
      {msg && <div className="mb-4 rounded-xl border border-brand-100 bg-brand-50 p-3.5 text-sm text-brand-700">{msg}</div>}
      <div className="space-y-4">
        {rows === null ? <p className="text-slate-500">Loading…</p> : rows.length === 0
          ? <Card><Empty icon="check" title="Nothing awaiting your approval">Proposed deals appear here when an incident needs you to buy or sell stock.</Empty></Card>
          : rows.map(d => <DealCard key={d.id} d={d} big={farmer} onDecide={decide} busy={busy === d.id} />)}
        {waiting.length > 0 && <h2 className="pt-2 text-sm font-semibold uppercase tracking-wide text-slate-400">Waiting for the other side</h2>}
        {waiting.map(d => <DealCard key={d.id} d={d} big={farmer} />)}
      </div>
    </div>
  )
}
