import { useEffect, useState } from 'react'
import { api } from '../api'
import { Card, PageHeader } from '../components/ui'

const LABEL: Record<string, string> = { agents: 'Gemini agents', rules: 'Rule-based fallback' }

export default function Eval() {
  const [d, setD] = useState<any | null | undefined>(undefined)
  useEffect(() => { api('/api/eval/latest').then(setD) }, [])
  if (d === undefined) return <p className="text-slate-500">Loading…</p>
  if (d === null) return <><PageHeader title="Evaluation" /><Card><p className="text-sm">No report yet. Run <code className="rounded bg-slate-100 px-1">python -m app.eval.run --reset</code> in <code>backend/</code> (wipes demo data). Add <code>--rules</code> for the rule-based baseline.</p></Card></>
  const runs: any[] = [...d.runs].sort((a, b) => (a.mode === 'agents' ? -1 : 1) - (b.mode === 'agents' ? -1 : 1))
  const groups = Object.keys(runs[0].metrics)
  return (
    <div>
      <PageHeader title="Evaluation" subtitle="Table 5 metrics. The agentic system is what ships; the rule-based path is its fallback and a deterministic baseline." />
      <div className="mb-4 flex flex-wrap gap-3 text-xs text-slate-500">
        {runs.map(r => <span key={r.file}><b className="text-slate-700">{LABEL[r.mode]}</b> · {r.created} · judge {r.judge}</span>)}
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        {groups.map(g => (
          <Card key={g} title={g}>
            <table className="w-full text-sm">
              <thead><tr className="text-left text-xs text-slate-400"><th className="pb-2 font-medium">Metric</th>{runs.map(r => <th key={r.mode} className="pb-2 text-right font-medium">{LABEL[r.mode]}</th>)}</tr></thead>
              <tbody>{Object.keys(runs[0].metrics[g]).map((k, i) => {
                const key = (r: any) => Object.keys(r.metrics[g])[i]
                return (
                  <tr key={k} className="border-t border-slate-100">
                    <td className="py-2 text-slate-600">{k.replace(/ \(judge:.*\)/, '')}</td>
                    {runs.map(r => { const v = r.metrics[g][key(r)]; return <td key={r.mode} className="py-2 text-right font-semibold text-ink">{v === null ? 'n/a' : `${v}%`}</td> })}
                  </tr>)
              })}</tbody>
            </table>
          </Card>))}
      </div>
    </div>
  )
}
