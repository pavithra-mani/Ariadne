import RagAnswer from './RagAnswer'
import { Badge } from './ui'

const PRI: Record<string, { box: string; chip: string; word: string }> = {
  P1: { box: 'border-red-200 bg-red-50', chip: 'bg-red-600', word: 'Urgent' },
  P2: { box: 'border-orange-200 bg-orange-50', chip: 'bg-orange-500', word: 'High' },
  P3: { box: 'border-amber-200 bg-amber-50', chip: 'bg-amber-500', word: 'Medium' },
  P4: { box: 'border-emerald-200 bg-emerald-50', chip: 'bg-emerald-600', word: 'Low' },
}
const human = (s: string) => s.replace(/_/g, ' ')

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return <section><h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">{title}</h4>{children}</section>
}
function LinkBtn({ id, onOpen }: { id: number; onOpen?: (id: number) => void }) {
  return onOpen ? <button onClick={() => onOpen(id)} className="font-semibold text-brand-600 hover:underline">#{id}</button> : <b>#{id}</b>
}
const Th = ({ children }: { children: React.ReactNode }) => <th className="py-2 pr-3 text-left text-xs font-medium text-slate-400">{children}</th>

export default function IncidentCard({ inc, onOpen, onClose }: { inc: any; onOpen?: (id: number) => void; onClose?: (id: number) => void }) {
  const p = inc.payload ?? {}
  const f = p.finding, adv = p.advisory, imp = p.supply_impact, mem = p.memory, risk = p.risk
  const pri = inc.priority ? PRI[inc.priority] : null

  if (inc.status === 'error')
    return <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800"><b>Something went wrong while analysing this.</b> {p.error}</div>

  return (
    <div className="space-y-6 text-sm">
      {pri ? (
        <div className={`flex items-center gap-4 rounded-xl border p-4 ${pri.box}`}>
          <div className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-xl text-lg font-bold text-white ${pri.chip}`}>{inc.priority}</div>
          <div className="min-w-0 flex-1">
            <div className="text-base font-semibold text-ink">{(adv?.headline ?? human(inc.kind)).replace(/ - priority P\d/, '')}</div>
            <div className="mt-0.5 text-slate-600">{pri.word} · {inc.severity} severity · {inc.urgency} urgency{adv?.structured_by === 'agent' && <span className="ml-2 text-xs text-slate-500">· 🤖 Gemini agent</span>}</div>
          </div>
          <div className="text-right text-xs text-slate-500"><div>Incident #{inc.id}</div><div className="mt-1"><Badge tone="violet">{human(inc.status)}</Badge></div></div>
        </div>
      ) : (
        <div className="flex items-center justify-between text-xs text-slate-400"><span>#{inc.id} · {human(inc.status)}</span>{adv?.structured_by && <span>{adv.structured_by === 'agent' ? '🤖 answered by the Gemini agent' : `formatted by ${adv.structured_by}`}</span>}</div>
      )}

      {f?.cause && (
        <div className="rounded-xl border border-sky-200 bg-sky-50 p-3.5 text-sky-900"><b>Opened automatically.</b> {f.cause}</div>
      )}

      {mem?.recurring && (
        <div className="rounded-xl border border-brand-100 bg-brand-50 p-3.5 text-brand-700">
          <b>This has happened before.</b> {mem.count} similar earlier incident(s): {mem.similar.map((s: any) => `#${s.incident_id} (${s.date})`).join(', ')}.
        </div>
      )}

      {f?.label && f.source !== 'cascade' && f.source !== 'stock_calculations' && (
        <Block title="What we found">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-lg font-semibold capitalize text-ink">{human(f.label)}</span>
            <span className="text-slate-500">{Math.round(f.confidence * 100)}% confident · {human(f.source)}</span>
            {f.is_stub && <Badge tone="reorder">demo classifier</Badge>}
            {f.uncertain && <Badge tone="critical">not sure</Badge>}
          </div>
          {risk?.rationale?.length > 0 && <p className="mt-1 text-slate-500">{risk.rationale.join(' · ')}</p>}
        </Block>
      )}
      {risk?.rationale?.length > 0 && (f?.source === 'stock_calculations' || f?.source === 'cascade') && (
        <Block title="Why this priority"><ul className="list-disc space-y-1 pl-5 text-slate-600">{risk.rationale.map((r: string, i: number) => <li key={i}>{r}</li>)}</ul></Block>
      )}

      {adv?.type === 'clarify' && (
        <div className="rounded-xl border border-sky-200 bg-sky-50 p-4 text-sky-900">
          <div className="text-xs font-semibold uppercase tracking-wide text-sky-600">Ariadne needs a bit more detail</div>
          <p className="mt-1 text-base font-medium">{adv.question}</p>
          <p className="mt-1 text-xs text-sky-700">Reply in the box above; nothing was assumed and no deals were proposed.</p>
        </div>
      )}

      {adv?.type === 'advisory' && (
        <Block title="What to do">
          <p className="mb-3 text-slate-600">{adv.diagnosis}</p>
          <ol className="list-decimal space-y-1.5 pl-5 text-slate-700">{adv.mitigation_steps.map((s: string, i: number) => (
            <li key={i}>{s}{adv.ungrounded_steps?.includes(i) && <span className="ml-2 rounded bg-amber-50 px-1.5 py-0.5 text-[11px] text-amber-700 ring-1 ring-amber-200">general advice, not found in the sources</span>}</li>))}</ol>
          {adv.follow_up?.length > 0 && <ul className="mt-3 list-disc space-y-1 pl-5 text-slate-500">{adv.follow_up.map((s: string, i: number) => <li key={i}>{s}</li>)}</ul>}
          {adv.escalate && <div className="mt-3 rounded-xl border border-red-200 bg-red-50 p-3.5 text-red-800"><b>{inc.role === 'mulberry_farm' ? 'Escalated: the silkworm farmers you supply were alerted.' : 'Escalated: your reelers were alerted.'}</b> {adv.escalation_reason}</div>}
        </Block>
      )}
      {adv?.type === 'answer' && (
        <Block title="Answer">
          {adv.abstained ? <RagAnswer rag={p.rag} /> : (<>
            <p className="text-slate-700">{adv.answer}</p>
            {adv.key_points?.length > 0 && <ul className="mt-2 list-disc space-y-1 pl-5 text-slate-600">{adv.key_points.map((s: string, i: number) => <li key={i}>{s}</li>)}</ul>}
          </>)}
        </Block>
      )}

      {imp?.n_affected > 0 && (
        <Block title={imp.gap !== undefined ? `Can the target be met? ${imp.target} kg in ${imp.horizon_days} days` : `Who is affected · ${imp.n_at_risk} of ${imp.n_affected} at risk`}>
          {imp.gap !== undefined && <p className="mb-2 text-slate-600">Own spare stock <b>{imp.own_buffer} kg</b> + linked reelers <b>{imp.linked_supply} kg</b> → {imp.gap > 0 ? <b className="text-red-600">short by {imp.gap} kg</b> : <b className="text-emerald-700">target can be met</b>}</p>}
          <div className="overflow-x-auto rounded-xl border border-slate-100"><table className="w-full">
            <thead className="bg-slate-50"><tr className="[&>th]:px-3">
              {(imp.gap !== undefined ? ['Reeler', 'Sellable', 'Spare capacity', 'Can supply'] : imp.affected[0]?.allocated !== undefined ? ['Partner', 'Needs', 'Gets', 'Cover (d)', 'Short by'] : ['Partner', 'Exposure', 'Cover (d)', 'To restock']).map((h: string) => <Th key={h}>{h}</Th>)}</tr></thead>
            <tbody>{imp.affected.map((a: any) => (
              <tr key={a.entity_id} className="border-t border-slate-100 [&>td]:px-3 [&>td]:py-2">
                <td>{a.name} <span className="text-slate-400">· {a.village}</span></td>
                {imp.gap !== undefined ? <><td>{a.sellable} kg</td><td>{a.spare_capacity} kg</td><td className="font-medium">{a.can_supply} kg</td></>
                  : a.allocated !== undefined ? <><td>{a.need} kg</td><td>{a.allocated} kg</td><td>{a.cover_days}</td><td className={a.shortfall > 0 ? 'font-medium text-red-600' : 'text-emerald-700'}>{a.shortfall} kg</td></>
                    : <><td>{a.exposure_qty} kg</td><td>{a.cover_days}</td><td className={a.shortfall > 0 ? 'font-medium text-red-600' : 'text-emerald-700'}>{a.shortfall} kg</td></>}
              </tr>))}</tbody></table></div>
          {p.outcome?.children?.length > 0 && <p className="mt-2 text-sm text-brand-700">Ariadne opened a recovery incident for {p.outcome.children.length} buyer{p.outcome.children.length === 1 ? '' : 's'} that fall below their reorder point: each is alerted, gets alternatives and routes, and decides on the proposed deals itself.</p>}
          <p className="mt-2 text-xs text-slate-400">{p.hidden_partners > 0 ? `${p.hidden_partners} partner(s) are outside your visibility, so only their numbers are shown. ` : ''}Every affected partner was alerted as soon as this incident was assessed.</p>
          {imp.stranded_cocoon > 0 && <p className="mt-2 text-amber-700">{imp.stranded_cocoon} kg of cocoons are stranded by reduced capacity and will degrade.</p>}
        </Block>
      )}

      {p.plans?.length > 0 && (
        <Block title="Recovery plan">
          <div className="space-y-2">{p.plans.map((c: any) => (
            <div key={c.idx} className="rounded-xl border border-slate-200 p-3.5">
              <div className="flex flex-wrap items-center gap-2">
                <span><b>{c.buyer_name}</b> needs <b>{c.qty} kg {c.product}</b></span>
                <Badge tone={c.status === 'resolved' ? 'ok' : c.status === 'partial' ? 'reorder' : 'critical'}>{c.status === 'resolved' ? 'fully sourced' : c.status}</Badge>
                <span className="text-xs text-slate-400">{c.covered} kg covered · {c.attempts.length} of max 5 searches</span>
              </div>
              {c.strategy && <div className="mt-1.5 text-xs text-slate-500"><Badge tone="violet">strategy: {c.strategy.replace('_', ' ')}</Badge> {c.strategy_reason}</div>}
              <ol className="mt-1.5 space-y-0.5 text-xs text-slate-500">{c.attempts.map((a: any) => (
                <li key={a.attempt}>Search {a.attempt}: within {a.radius_km} km → {a.n_candidates} candidate(s), {a.covered_routed} kg routable over {a.total_km} km</li>))}</ol>
            </div>))}</div>
          {p.outcome?.unresolved?.length > 0 && <div className="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-3.5 text-amber-900"><b>Needs human follow-up:</b> {p.outcome.unresolved.map((u: any) => `${u.qty} kg ${u.product} for ${u.buyer_name} (${u.reason})`).join('; ')}</div>}
          {inc.status === 'awaiting_approval' && <div className="mt-3 rounded-xl border border-brand-100 bg-brand-50 p-3.5 text-brand-700">⏸ Paused for approval by <b>{[...new Set(p.plans.filter((c: any) => c.deals?.length).map((c: any) => c.approver))].join(', ')}</b>. No stock or balance changes until then.</div>}
          {p.outcome?.executed?.length > 0 && <p className="mt-3 text-emerald-700">✔ Executed deals: {p.outcome.executed.map((d: number) => `#${d}`).join(', ')}</p>}
          {p.outcome?.rejected?.length > 0 && <p className="mt-1 text-red-700">✖ Rejected deals: {p.outcome.rejected.map((d: number) => `#${d}`).join(', ')}. Nothing changed.</p>}
        </Block>
      )}

      {inc.lineage && (inc.lineage.parent || inc.lineage.children?.length > 0 || inc.lineage.hidden_children > 0 || inc.lineage.has_hidden_parent) && (
        <Block title="Linked incidents">
          <ul className="space-y-1.5 text-slate-600">
            {inc.lineage.parent && <li>↑ Caused by <LinkBtn id={inc.lineage.parent.id} onOpen={onOpen} /> {human(inc.lineage.parent.kind)} at {inc.lineage.parent.entity}</li>}
            {inc.lineage.has_hidden_parent && <li>↑ Caused by an upstream incident outside your visibility.</li>}
            {inc.lineage.children.map((c: any) => <li key={c.id}>↓ Led to <LinkBtn id={c.id} onOpen={onOpen} /> {human(c.kind)} at {c.entity} <Badge>{human(c.status)}</Badge></li>)}
            {inc.lineage.hidden_children > 0 && <li>↓ Led to {inc.lineage.hidden_children} more downstream incident(s) outside your visibility.</li>}
          </ul>
        </Block>
      )}

      {p.rag && adv?.type === 'advisory' && p.rag.passages?.length > 0 && (
        <details><summary className="text-xs font-medium text-brand-600">Sources used ({p.rag.passages.length})</summary><div className="mt-2"><RagAnswer rag={{ ...p.rag, points: [] }} /></div></details>)}

      {onClose && !['awaiting_approval', 'closed'].includes(inc.status) && inc.is_issue && inc.kind !== 'low_stock' && (
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-3.5">
          <button onClick={() => onClose(inc.id)} className="rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-100">Mark as recovered</button>
          <span className="ml-3 text-xs text-slate-500">Stops this incident from reducing your buyers' supply outlook.</span>
        </div>)}

      {inc.trace?.length > 0 && (
        <details><summary className="text-xs font-medium text-brand-600">How Ariadne got here · agent trace ({inc.trace.length} steps)</summary>
          <ol className="mt-3 space-y-2 border-l-2 border-brand-100 pl-4">{inc.trace.map((t: any, i: number) => (
            <li key={i} className="text-xs"><b className="text-slate-700">{human(t.node)}</b> <span className="text-slate-400">{t.ms} ms</span>
              <div className="text-slate-500">{t.summary}{t.tools?.length > 0 && <span className="text-brand-600"> · tools: {t.tools.join(', ')}</span>}</div>
              {t.llm?.length > 0 && <div className="mt-0.5 text-violet-700">🤖 {t.llm.map((c: any) => `${c.purpose} · ${c.model} · ${(c.ms / 1000).toFixed(1)}s`).join('  ›  ')}</div>}
              {t.agent?.length > 0 && <ol className="mt-1 space-y-0.5 border-l border-violet-200 pl-3">{t.agent.map((a: any, j: number) => (
                <li key={j} className="text-slate-600"><span className="font-medium text-violet-700">{a.tool}</span>({Object.values(a.args).map(String).join(', ').slice(0, 60)}) <span className="text-slate-400">→ {String(a.result).slice(0, 90)}</span></li>))}</ol>}</li>))}</ol></details>)}
    </div>
  )
}
