import { Badge } from './ui'

export default function RagAnswer({ rag }: { rag: any }) {
  if (!rag) return null
  if (rag.abstained)
    return (
      <div className="rounded-xl border border-gold-200 bg-gold-50 p-4 text-sm text-gold-700">
        <b>I don't have reliable information on this.</b> {rag.reason} Please consult an expert or your local sericulture office.
      </div>
    )
  return (
    <div className="space-y-3 text-sm">
      {rag.points?.length > 0 && <ul className="list-disc space-y-1.5 pl-5 text-slate-700">
        {rag.points.map((p: any, i: number) => <li key={i}>{p.text} <sup className="font-semibold text-brand-600">[{p.citation}]</sup></li>)}</ul>}
      <div className="space-y-1 border-t border-slate-100 pt-2">
        {rag.passages.map((p: any, i: number) => (
          <div key={p.id} className="text-xs text-slate-500"><b className="text-brand-600">[{i + 1}]</b> {p.title.length > 90 ? p.title.slice(0, 90) + '…' : p.title}
            {p.topic && <> · <Badge>{p.topic}</Badge></>}
            {p.origin?.startsWith('http')
              ? <> · <a href={p.origin} target="_blank" rel="noreferrer" className="text-brand-600 underline">{p.publisher?.split(',')[0] || 'source'} ↗</a></>
              : <> · <Badge tone="reorder">placeholder text, not an official source</Badge></>}</div>))}
        {rag.queries_tried.length > 1 && <div className="text-xs text-slate-400">Query rewritten {rag.queries_tried.length - 1}×: “{rag.queries_tried.at(-1)}”</div>}
      </div>
    </div>
  )
}
