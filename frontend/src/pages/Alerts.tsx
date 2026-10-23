import { useEffect, useState } from 'react'
import { api, post } from '../api'
import { Card, Empty, PageHeader, btn } from '../components/ui'

const STYLE: Record<string, [string, string]> = {
  alert: ['bg-red-500', 'At risk'], warning: ['bg-amber-500', 'Heads-up'], deal: ['bg-emerald-500', 'Deal'], info: ['bg-sky-500', 'Info'],
}

export default function Alerts() {
  const [items, setItems] = useState<any[] | null>(null)
  const load = () => api('/api/notifications').then(setItems)
  useEffect(() => { load() }, [])
  const readAll = async () => { await post('/api/notifications/read'); load() }
  return (
    <div>
      <PageHeader title="Alerts" subtitle="Told the moment a partner upstream or downstream reports a problem that touches you."
        right={<button onClick={readAll} className={btn.ghost}>Mark all read</button>} />
      <Card pad={false}>
        {items === null ? <p className="p-5 text-slate-500">Loading…</p> : items.length === 0
          ? <Empty icon="bell" title="No alerts">When a supplier, buyer or partner reports an incident that affects you, it shows up here immediately.</Empty>
          : <ul className="divide-y divide-slate-100">{items.map(n => {
            const [dot, label] = STYLE[n.level] ?? STYLE.info
            return (
              <li key={n.id} className={`flex gap-3 px-5 py-4 ${n.read ? '' : 'bg-brand-50/50'}`}>
                <span className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${dot}`} />
                <div className="flex-1"><div className="text-sm text-slate-700">{n.message}</div>
                  <div className="mt-1 text-xs text-slate-400">{label} · {new Date(n.created_at).toLocaleString()}{n.incident_id && ` · incident #${n.incident_id}`}</div></div>
              </li>)
          })}</ul>}
      </Card>
    </div>
  )
}
