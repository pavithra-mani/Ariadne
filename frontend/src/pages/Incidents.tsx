import { useEffect, useState } from 'react'
import { api, post } from '../api'
import IncidentCard from '../components/IncidentCard'
import { Badge, Card, Empty, PageHeader } from '../components/ui'

const PRI_TONE: Record<string, string> = { P1: 'critical', P2: 'degrading', P3: 'reorder', P4: 'ok' }

export default function Incidents() {
  const [rows, setRows] = useState<any[] | null>(null)
  const [sel, setSel] = useState<any>(null)
  useEffect(() => { api('/api/incidents').then(setRows) }, [])
  const open = async (id: number) => setSel(await api(`/api/incidents/${id}`))
  const close = async (id: number) => { await post(`/api/incidents/${id}/close`); await open(id); api('/api/incidents').then(setRows) }
  return (
    <div>
      <PageHeader title="Incidents" subtitle="Problems you reported and ones Ariadne opened for you by itself, with the advice, risk rating and offers for each." />
      <div className="grid gap-4 lg:grid-cols-[300px_1fr]">
        <Card pad={false}>
          {rows === null ? <p className="p-5 text-slate-500">Loading…</p> : rows.length === 0 ? <Empty icon="flag" title="No incidents yet">Use the Assistant to report one.</Empty> : (
            <ul className="divide-y divide-slate-100">{rows.map(r => (
              <li key={r.id}><button onClick={() => open(r.id)} className={`w-full px-4 py-3 text-left transition hover:bg-slate-50 ${sel?.id === r.id ? 'bg-brand-50' : ''}`}>
                <div className="flex items-center gap-2"><span className="font-medium text-ink">#{r.id}</span><span className="text-sm capitalize text-slate-600">{r.kind.replace(/_/g, ' ')}</span>
                  {r.priority && <Badge tone={PRI_TONE[r.priority]}>{r.priority}</Badge>}{r.parent_id && <Badge tone="blue">auto</Badge>}</div>
                <div className="mt-0.5 truncate text-xs text-slate-500">{r.message || '(photo)'}</div>
                <div className="mt-0.5 text-xs text-slate-400">{r.status.replace(/_/g, ' ')}</div></button></li>))}</ul>)}
        </Card>
        <Card>{sel ? <IncidentCard inc={sel} onOpen={open} onClose={close} /> : <Empty icon="flag" title="Select an incident" />}</Card>
      </div>
    </div>
  )
}
