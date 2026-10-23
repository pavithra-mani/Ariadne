import { useEffect, useState } from 'react'
import { api, post } from '../api'
import RagAnswer from '../components/RagAnswer'
import { Card, PageHeader, btn, input } from '../components/ui'

const EXAMPLES = ['White powder on the underside of mulberry leaves', 'Silkworms have milky fluid and climb the tray edge',
  'How should fresh cocoons be stored?', 'My yarn stock is falling, what should I do?', 'What is the capital of France?']

export default function Knowledge() {
  const [q, setQ] = useState('')
  const [topic, setTopic] = useState('')
  const [res, setRes] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const [stats, setStats] = useState<any>(null)
  useEffect(() => { api('/api/knowledge/stats').then(setStats) }, [])
  const ask = async (question = q) => {
    if (!question.trim()) return
    setQ(question); setBusy(true)
    try { setRes(await post('/api/knowledge/ask', { question, topic: topic || null })) } finally { setBusy(false) }
  }
  return (
    <div>
      <PageHeader title="Knowledge base" subtitle={stats ? `${stats.documents} documents · ${stats.chunks} passages. Answers are retrieved, graded and cited, or refused.` : ''} />
      <Card>
        <form onSubmit={e => { e.preventDefault(); ask() }} className="flex gap-2">
          <input className={`${input} flex-1`} placeholder="Ask about disease, rearing, cocoon storage, reeling…" value={q} onChange={e => setQ(e.target.value)} />
          <select className={input} value={topic} onChange={e => setTopic(e.target.value)}>
            <option value="">All topics</option>{stats && Object.keys(stats.topics).map(t => <option key={t}>{t}</option>)}</select>
          <button disabled={busy} className={btn.primary}>{busy ? 'Searching…' : 'Ask'}</button>
        </form>
        <div className="mt-3 flex flex-wrap gap-2">{EXAMPLES.map(e => <button key={e} onClick={() => ask(e)} className="rounded-full border border-slate-200 px-3 py-1 text-xs text-slate-600 hover:border-brand-500 hover:text-brand-700">{e}</button>)}</div>
      </Card>
      {res && <Card className="mt-4" title="Answer"><RagAnswer rag={res} /></Card>}
    </div>
  )
}
