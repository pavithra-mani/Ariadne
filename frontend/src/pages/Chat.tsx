import { useRef, useState } from 'react'
import { api } from '../api'
import { useAuth } from '../auth'
import IncidentCard from '../components/IncidentCard'
import { Card, PageHeader, btn, input } from '../components/ui'

const PROMPTS: Record<string, string[]> = {
  mulberry_farm: ['White powder on the underside of my mulberry leaves', 'Brown spots with a yellow halo on leaves', 'How do I prevent leaf rust?'],
  silkworm_farm: ['My larvae are restless with milky fluid', 'Larvae stopped feeding and are vomiting', 'How should fresh cocoons be stored?'],
  reeler: ['How do I raise falling yarn stock?', 'How should raw silk yarn be stored?'],
  spinner: ['How do I handle a demand surge?', 'How should I plan yarn safety stock?'],
}

const Num = ({ v, set, ph }: { v: string; set: (s: string) => void; ph: string }) =>
  <input type="number" min={0} value={v} onChange={e => set(e.target.value)} placeholder={ph} className={`${input} w-40`} />

export default function Chat() {
  const { user } = useAuth()
  const [msg, setMsg] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [pct, setPct] = useState('20')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [itype, setItype] = useState('')
  const [v1, setV1] = useState('')
  const [v2, setV2] = useState('')
  const [thread, setThread] = useState<{ q: string; img?: string; inc: any }[]>([])
  const fileRef = useRef<HTMLInputElement>(null)
  const farmer = user?.role === 'mulberry_farm' || user?.role === 'silkworm_farm'

  const send = async (text = msg) => {
    const structured = (user?.role === 'reeler' && itype) || (user?.role === 'spinner' && v1)
    if (!text.trim() && !file && !structured) return
    setBusy(true); setErr('')
    const fd = new FormData()
    fd.append('message', text)
    if (file) fd.append('image', file)
    if (farmer) fd.append('fields', JSON.stringify({ affected_pct: Number(pct) }))
    if (user?.role === 'reeler' && itype) {
      const f: any = { incident_type: itype }
      if (itype === 'low_yarn_output') { if (v1) f.reduction_pct = Number(v1); if (v2) f.duration_days = Number(v2) }
      if (itype === 'cocoon_shortage') { if (v1) f.quantity_kg = Number(v1); if (v2) f.duration_days = Number(v2) }
      if (itype === 'delivery_delay') { if (v1) f.delay_days = Number(v1); if (v2) f.quantity_kg = Number(v2) }
      fd.append('fields', JSON.stringify(f))
    }
    if (user?.role === 'spinner' && (v1 || v2)) fd.append('fields', JSON.stringify({ ...(v1 && { target_qty: Number(v1) }), ...(v2 && { horizon_days: Number(v2) }) }))
    try {
      const inc = await api('/api/chat', { method: 'POST', body: fd })
      setThread(t => [{ q: text || (file ? '(photo)' : '(structured report)'), img: file ? URL.createObjectURL(file) : undefined, inc }, ...t])
      setMsg(''); setFile(null); if (fileRef.current) fileRef.current.value = ''
    } catch (e: any) { setErr(e.message) } finally { setBusy(false) }
  }

  return (
    <div>
      <PageHeader title="Assistant" subtitle={farmer ? 'Describe a problem or upload a photo. Ariadne diagnoses, rates the risk and alerts everyone it affects.' : 'Report an issue or ask a question. Affected partners are alerted immediately.'} />
      <Card>
        <form onSubmit={e => { e.preventDefault(); send() }} className="space-y-4">
          <textarea className={`${input} w-full`} rows={3} value={msg} onChange={e => setMsg(e.target.value)}
            placeholder={farmer ? 'e.g. White powder on the underside of my leaves…' : 'Describe your issue or ask a question…'} />
          <div className="flex flex-wrap items-center gap-3">
            {farmer && (<>
              <label className="flex cursor-pointer items-center gap-2 rounded-lg border border-dashed border-slate-300 px-3 py-2 text-sm text-slate-600 hover:border-brand-500">
                <span>📷 {file ? file.name : 'Add a photo'}</span>
                <input ref={fileRef} type="file" accept="image/*" className="hidden" onChange={e => setFile(e.target.files?.[0] ?? null)} /></label>
              <label className="flex items-center gap-2 text-sm text-slate-600">Affected ≈
                <input type="number" min={1} max={100} value={pct} onChange={e => setPct(e.target.value)} className={`${input} w-20 py-1.5`} />%</label>
            </>)}
            {user?.role === 'reeler' && (<>
              <select value={itype} onChange={e => { setItype(e.target.value); setV1(''); setV2('') }} className={input}>
                <option value="">Free text</option><option value="low_yarn_output">Low yarn output (factory issue)</option>
                <option value="cocoon_shortage">Low cocoon supply</option><option value="delivery_delay">Delivery delay</option></select>
              {itype === 'low_yarn_output' && <><Num v={v1} set={setV1} ph="output drop %" /><Num v={v2} set={setV2} ph="for how many days" /></>}
              {itype === 'cocoon_shortage' && <><Num v={v1} set={setV1} ph="cocoon short (kg)" /><Num v={v2} set={setV2} ph="over days" /></>}
              {itype === 'delivery_delay' && <><Num v={v1} set={setV1} ph="delay (days)" /><Num v={v2} set={setV2} ph="yarn delayed (kg)" /></>}
            </>)}
            {user?.role === 'spinner' && (<><span className="text-sm text-slate-500">Demand surge / new target</span><Num v={v1} set={setV1} ph="target yarn (kg)" /><Num v={v2} set={setV2} ph="within days" /></>)}
            <button disabled={busy} className={`${btn.primary} ml-auto`}>{busy ? 'Analysing…' : 'Send'}</button>
          </div>
          <div className="flex flex-wrap gap-2">{(PROMPTS[user?.role ?? ''] ?? []).map(p => (
            <button type="button" key={p} onClick={() => send(p)} className="rounded-full border border-slate-200 px-3 py-1 text-xs text-slate-600 hover:border-brand-500 hover:text-brand-700">{p}</button>))}</div>
          {err && <p className="text-sm text-red-600">{err}</p>}
        </form>
      </Card>
      <div className="mt-6 space-y-6">{thread.map((t, i) => (
        <div key={t.inc.id + '-' + i} className="space-y-3">
          <div className="flex justify-end"><div className="max-w-[80%] rounded-2xl rounded-tr-sm bg-brand-600 px-4 py-2.5 text-sm text-white">
            {t.img && <img src={t.img} alt="upload" className="mb-2 h-28 rounded-lg" />}{t.q}</div></div>
          <Card><IncidentCard inc={t.inc} /></Card>
        </div>))}</div>
    </div>
  )
}
