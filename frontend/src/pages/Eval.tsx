import { useEffect, useState } from 'react'
import { api } from '../api'
import { Card, PageHeader } from '../components/ui'

export default function Eval() {
  const [d, setD] = useState<any | null | undefined>(undefined)
  useEffect(() => { api('/api/eval/latest').then(setD) }, [])
  if (d === undefined) return <p className="text-slate-500">Loading…</p>
  if (d === null) return <><PageHeader title="Evaluation" /><Card><p className="text-sm">No report yet. Run <code className="rounded bg-slate-100 px-1">python -m app.eval.run --reset</code> in <code>backend/</code> (wipes demo data).</p></Card></>
  return (
    <div>
      <PageHeader title="Evaluation" subtitle={`${d.file} · judge: ${d.judge} · Groq ${d.groq ? 'on' : 'off'} · ${d.runs} run(s) on file`} />
      <div className="grid gap-4 md:grid-cols-2">
        {Object.entries(d.metrics).map(([group, ms]: [string, any]) => (
          <Card key={group} title={group}>
            {Object.entries(ms).map(([k, v]: [string, any]) => (
              <div key={k} className="flex items-center justify-between border-b border-slate-100 py-2.5 text-sm last:border-0">
                <span className="text-slate-600">{k}</span><b className="text-ink">{v === null ? 'n/a' : `${v}%`}</b>
              </div>))}
          </Card>))}
      </div>
    </div>
  )
}
