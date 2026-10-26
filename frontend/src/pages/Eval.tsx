import { useEffect, useState } from 'react'
import { api } from '../api'
import { Card, Empty, PageHeader } from '../components/ui'

const LABEL: Record<string, string> = { agents: 'Gemini agents', rules: 'Rule-based fallback' }

export default function Eval() {
  const [d, setD] = useState<any | null | undefined>(undefined)
  const [err, setErr] = useState('')
  useEffect(() => { api('/api/eval/latest').then(setD).catch(e => setErr(e.message)) }, [])
  const head = <PageHeader title="Evaluation" subtitle="How well Ariadne answers questions and routes problems, measured on a fixed test set." />
  if (err) return <>{head}<Card><p className="text-sm text-red-600">Could not load the report: {err}</p></Card></>
  if (d === undefined) return <>{head}<p className="text-sm text-slate-500">Loading…</p></>
  const runs: any[] = Array.isArray(d?.runs) ? d.runs.filter((r: any) => r && r.metrics && Object.keys(r.metrics).length) : []
  if (!runs.length) return (
    <>{head}<Card><Empty icon="chart" title="No report yet">
      Run <code className="rounded bg-brand-50 px-1.5 py-0.5 text-brand-700">python -m app.eval.run --reset</code> in <code>backend/</code> (this wipes demo data). Add <code>--rules</code> for the rule-based baseline.
      Agent and optimiser results are in <code>docs/AGENTICNESS.md</code>.
    </Empty></Card></>
  )
  runs.sort((a, b) => (a.mode === 'agents' ? -1 : 1) - (b.mode === 'agents' ? -1 : 1))
  const groups = Object.keys(runs[0].metrics)
  const cell = (r: any, g: string, i: number) => {
    const keys = Object.keys(r.metrics?.[g] ?? {})
    const v = keys[i] !== undefined ? r.metrics[g][keys[i]] : null
    return v === null || v === undefined ? 'n/a' : `${v}%`
  }
  return (
    <div>
      {head}
      <div className="mb-4 flex flex-wrap gap-x-5 gap-y-1 text-xs text-slate-500">
        {runs.map(r => <span key={r.file}><b className="text-brand-800">{LABEL[r.mode] ?? r.mode}</b> · {r.created ?? 'undated'}{r.judge ? ` · judge ${r.judge}` : ''}</span>)}
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        {groups.map(g => (
          <Card key={g} title={g}>
            <table className="w-full text-sm">
              <thead><tr className="text-left text-xs text-slate-400"><th className="pb-2 font-medium">Metric</th>{runs.map(r => <th key={r.mode} className="pb-2 text-right font-medium">{LABEL[r.mode] ?? r.mode}</th>)}</tr></thead>
              <tbody>{Object.keys(runs[0].metrics[g] ?? {}).map((k, i) => (
                <tr key={k} className="border-t border-brand-50">
                  <td className="py-2 text-slate-600">{k.replace(/ \(judge:.*\)/, '')}</td>
                  {runs.map(r => <td key={r.mode} className="py-2 text-right font-semibold text-ink">{cell(r, g, i)}</td>)}
                </tr>))}</tbody>
            </table>
          </Card>))}
      </div>
    </div>
  )
}
