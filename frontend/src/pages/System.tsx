import { useEffect, useState } from 'react'
import { api, post } from '../api'
import { Badge, Card, PageHeader, btn } from '../components/ui'

export default function System() {
  const [s, setS] = useState<any>(null)
  const [msg, setMsg] = useState('')
  const [consts, setConsts] = useState<any[]>([])
  const [busy, setBusy] = useState(false)
  const [rep, setRep] = useState<Record<string, string> | null>(null)
  const loadConsts = () => api('/api/system/constants').then(setConsts)
  useEffect(() => { api('/api/system/status').then(setS); loadConsts() }, [])
  const refresh = async () => {
    setBusy(true)
    try { setRep(await post('/api/system/constants/refresh')); await loadConsts() } catch (e: any) { setMsg(e.message) } finally { setBusy(false) }
  }
  const reset = async () => {
    if (!confirm('Wipe all incidents, deals, ledger and notifications and restore the seeded demo network?')) return
    try { await post('/api/system/reset-demo'); setMsg('Demo data restored.') } catch (e: any) { setMsg(e.message) }
  }
  if (!s) return <p className="text-slate-500">Loading…</p>
  const row = (k: string, v: React.ReactNode) => <div key={k} className="flex items-center justify-between border-b border-slate-100 py-3 text-sm last:border-0"><span className="text-slate-600">{k}</span><span>{v}</span></div>
  return (
    <div>
      <PageHeader title="System" subtitle="What is live and what is still a stand-in: AI models, disease models, and the prices and conversion ratios Ariadne uses." />
      <Card>
        {row('Gemini agents', s.llm?.gemini ? <Badge tone="ok">live · {s.llm.model}</Badge> : <Badge tone="reorder">off (rule-based fallback)</Badge>)}
        {s.llm?.gemini && row('LLM calls this session', `${s.llm.ok} ok · ${s.llm.rate_limited} rate-limited · ${s.llm.retried} retried · ${s.llm.failed} failed · ${s.llm.fallbacks} fallbacks · ${s.llm.tokens_in + s.llm.tokens_out} tokens`)}
        {row('Groq structuring', s.groq ? <Badge tone="ok">live</Badge> : <Badge tone="reorder">template fallback (no API key)</Badge>)}
        {row('LangSmith tracing', s.langsmith ? <Badge tone="ok">on</Badge> : <Badge tone="slate">off · local trace only</Badge>)}
        {Object.entries(s.classifiers).map(([c, v]) => row(`${c} disease classifier`, v === 'model' ? <Badge tone="ok">trained model</Badge> : v === 'gemini' ? <Badge tone="violet">Gemini vision (stand-in)</Badge> : <Badge tone="reorder">stub</Badge>))}
        {row('Knowledge base chunks', s.knowledge_chunks)}
        {row('Max alternative-source searches', s.max_searches)}
        {row('LLM calls (groq / repaired / template)', `${s.llm_stats.groq_ok} / ${s.llm_stats.repaired} / ${s.llm_stats.fallback}`)}
      </Card>
      <Card className="mt-4" title="Data & prices" subtitle="Prices come from the Central Silk Board bulletin when Ariadne starts (and daily). If a source is down or gives an odd value, the last good value or the default is kept."
        right={<button onClick={refresh} disabled={busy} className={btn.ghost}>{busy ? 'Checking…' : 'Refresh prices now'}</button>}>
        {rep && <div className="mb-3 rounded-lg bg-brand-50 px-3 py-2 text-xs text-brand-700">{Object.entries(rep).map(([k, v]) => `${k.replace('price_', '')}: ${v}`).join(' · ')}</div>}
        <div className="overflow-x-auto"><table className="w-full text-sm">
          <thead><tr className="border-b border-slate-100 text-left text-xs text-slate-400"><th className="py-2 pr-3 font-medium">Item</th><th className="py-2 pr-3 font-medium">Value</th><th className="py-2 pr-3 font-medium">Source</th></tr></thead>
          <tbody>{consts.map(c => (
            <tr key={c.name} className="border-b border-slate-50 align-top last:border-0">
              <td className="py-2.5 pr-3"><div className="font-medium text-ink">{c.name.replace(/_/g, ' ')}</div><div className="text-xs text-slate-400">{c.unit}</div></td>
              <td className="py-2.5 pr-3 font-medium text-ink">{c.value}</td>
              <td className="py-2.5 pr-3"><Badge tone={c.live ? 'ok' : 'slate'}>{c.live ? 'live' : 'default'}</Badge>
                <div className="mt-1 text-xs text-slate-500">{c.live ? <>{c.source}{c.fetched_at && <> · {new Date(c.fetched_at + 'Z').toLocaleDateString()}</>}</> : c.note}</div></td>
            </tr>))}</tbody></table></div>
      </Card>
      <Card className="mt-4" title="Demo data" subtitle="Restore the seeded network between rehearsals.">
        <div className="flex items-center gap-3">
          <button onClick={reset} className={btn.bad}>Reset demo data</button>{msg && <span className="text-sm text-slate-500">{msg}</span>}
        </div>
      </Card>
    </div>
  )
}
