import { useEffect, useState } from 'react'
import { api, post } from '../api'
import DealCard from '../components/DealCard'
import { Card, Empty, PageHeader } from '../components/ui'

export default function Approvals() {
  const [rows, setRows] = useState<any[] | null>(null)
  const [busy, setBusy] = useState<number | null>(null)
  const [msg, setMsg] = useState('')
  const load = () => api('/api/approvals').then(setRows)
  useEffect(() => { load() }, [])
  const decide = async (id: number, approve: boolean) => {
    setBusy(id); setMsg('')
    try {
      const r = await post(`/api/deals/${id}/decision`, { approve })
      setMsg(r.graph_resumed ? `All decisions are in. Incident #${r.incident?.id} is now ${r.incident?.status.replace(/_/g, ' ')}.` : `Deal #${id} ${approve ? 'approved' : 'rejected'}. Waiting for the remaining decisions.`)
      await load()
    } catch (e: any) { setMsg(e.message) } finally { setBusy(null) }
  }
  return (
    <div>
      <PageHeader title="Approvals" subtitle="Ariadne never changes stock or balances on its own. Every proposed deal waits here for a human." />
      {msg && <div className="mb-4 rounded-xl border border-brand-100 bg-brand-50 p-3.5 text-sm text-brand-700">{msg}</div>}
      <div className="space-y-4">
        {rows === null ? <p className="text-slate-500">Loading…</p> : rows.length === 0
          ? <Card><Empty icon="check" title="Nothing awaiting your approval">Proposed deals appear here when an incident needs you to buy or sell stock.</Empty></Card>
          : rows.map(d => <DealCard key={d.id} d={d} onDecide={decide} busy={busy === d.id} />)}
      </div>
    </div>
  )
}
