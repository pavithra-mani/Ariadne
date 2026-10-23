import { useEffect, useState } from 'react'
import { api, post } from '../api'
import { Badge, Card, PageHeader, btn } from '../components/ui'

export default function System() {
  const [s, setS] = useState<any>(null)
  const [msg, setMsg] = useState('')
  useEffect(() => { api('/api/system/status').then(setS) }, [])
  const reset = async () => {
    if (!confirm('Wipe all incidents, deals, ledger and notifications and restore the seeded demo network?')) return
    try { await post('/api/system/reset-demo'); setMsg('Demo data restored.') } catch (e: any) { setMsg(e.message) }
  }
  if (!s) return <p className="text-slate-500">Loading…</p>
  const row = (k: string, v: React.ReactNode) => <div key={k} className="flex items-center justify-between border-b border-slate-100 py-3 text-sm last:border-0"><span className="text-slate-600">{k}</span><span>{v}</span></div>
  return (
    <div>
      <PageHeader title="System" subtitle="What is live and what is still a stand-in." />
      <Card>
        {row('Groq structuring', s.groq ? <Badge tone="ok">live</Badge> : <Badge tone="reorder">template fallback (no API key)</Badge>)}
        {row('LangSmith tracing', s.langsmith ? <Badge tone="ok">on</Badge> : <Badge tone="slate">off · local trace only</Badge>)}
        {Object.entries(s.classifiers).map(([c, v]) => row(`${c} disease classifier`, v === 'model' ? <Badge tone="ok">trained model</Badge> : <Badge tone="reorder">stub</Badge>))}
        {row('Knowledge base chunks', s.knowledge_chunks)}
        {row('Max alternative-source searches', s.max_searches)}
        {row('LLM calls (groq / repaired / template)', `${s.llm_stats.groq_ok} / ${s.llm_stats.repaired} / ${s.llm_stats.fallback}`)}
      </Card>
      <Card className="mt-4" title="Demo data" subtitle="Restore the seeded network between rehearsals.">
        <div className="flex items-center gap-3">
          <button onClick={reset} className={btn.bad}>Reset demo data</button>{msg && <span className="text-sm text-slate-500">{msg}</span>}
        </div>
      </Card>
    </div>
  )
}
