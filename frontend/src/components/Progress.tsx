const STEP: Record<string, string> = {
  intake: 'Reading your report…', triage_supervisor: 'Deciding who should look at this…',
  mulberry_agent: 'Reading your photo and symptoms…', silkworm_agent: 'Reading your photo and symptoms…',
  reeler_agent: 'Working out the effect on your output…', spinner_agent: 'Working out your demand…', stock_monitor_agent: 'Checking your stock…',
  agentic_rag: 'Looking up guidance…', risk_assessment: 'Rating how serious it is…', supply_impact: 'Checking who is affected…',
  health_operational_impact: 'Checking who is affected…', advisory_action_plan: 'Writing your advice…', notify_affected: 'Alerting affected partners…',
  propagate_downstream: 'Checking everyone downstream…', inventory_check: 'Checking stock for replacements…',
  alternative_sources: 'Searching for other suppliers and buyers…', routing_ortools: 'Planning pick-up routes…', propose_deals: 'Sending offers…',
}
const ORDER = Object.keys(STEP)

/** Live progress for an incident that is still running: friendly text for the latest finished step. */
export default function Progress({ inc }: { inc: any }) {
  const done: string[] = (inc?.trace ?? []).map((t: any) => t.node)
  const last = [...done].reverse().find(n => STEP[n])
  const idx = last ? ORDER.indexOf(last) : -1
  const next = ORDER[Math.min(idx + 1, ORDER.length - 1)]
  return (
    <div className="flex items-center gap-3 rounded-xl border border-brand-100 bg-brand-50 p-4 text-brand-700">
      <span className="h-5 w-5 shrink-0 animate-spin rounded-full border-2 border-brand-200 border-t-brand-600" />
      <div><div className="text-sm font-semibold">{STEP[next] ?? 'Ariadne is working…'}</div>
        <div className="text-xs text-brand-600/80">{done.length ? `${done.length} step${done.length === 1 ? '' : 's'} done` : 'Starting…'}. You can leave this page; the result will be in Incidents.</div></div>
    </div>
  )
}
