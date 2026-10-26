import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { useAuth } from '../auth'
import IncidentCard from '../components/IncidentCard'
import Progress from '../components/Progress'
import { Card, Icon, PageHeader, btn, input } from '../components/ui'
import { isFarmer } from '../types'

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
  const [thread, setThread] = useState<{ q: string; img?: string; inc: any; slow?: boolean }[]>([])
  const fileRef = useRef<HTMLInputElement>(null)
  const farmer = isFarmer(user?.role)
  const started = useRef<Record<number, number>>({})

  // poll every incident that is still running until it finishes (give up after ~3 minutes)
  useEffect(() => {
    const running = thread.filter(t => t.inc.status === 'running' && !t.slow)
    if (!running.length) return
    const timer = setInterval(async () => {
      for (const t of running) {
        const id = t.inc.id
        try {
          const fresh = await api(`/api/incidents/${id}`)
          const slow = fresh.status === 'running' && Date.now() - (started.current[id] ?? Date.now()) > 180000
          setThread(th => th.map(x => x.inc.id === id ? { ...x, inc: fresh, slow } : x))
        } catch { /* keep polling */ }
      }
    }, 1500)
    return () => clearInterval(timer)
  }, [thread])

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
      started.current[inc.id] = Date.now()
      setThread(t => [{ q: text || (file ? '(photo)' : '(structured report)'), img: file ? URL.createObjectURL(file) : undefined, inc }, ...t])
      setMsg(''); setFile(null); if (fileRef.current) fileRef.current.value = ''
    } catch (e: any) { setErr(e.message) } finally { setBusy(false) }
  }

  return (
    <div>
      <PageHeader title={farmer ? 'Report a problem' : 'Assistant'} subtitle={farmer ? 'Send a photo of the problem. Ariadne tells you what it is, what to do, and warns the people it affects.' : 'Report an issue or ask a question. Affected partners are alerted immediately.'} />
      {farmer ? (
        <Card>
          <form onSubmit={e => { e.preventDefault(); send() }} className="space-y-5">
            <input ref={fileRef} id="photo" type="file" accept="image/*" capture="environment" className="hidden" onChange={e => setFile(e.target.files?.[0] ?? null)} />
            <label htmlFor="photo" className="flex cursor-pointer flex-col items-center justify-center gap-2 rounded-2xl border-2 border-dashed border-brand-200 bg-brand-50/60 px-4 py-8 text-center text-brand-700 active:bg-brand-100">
              {file ? <img src={URL.createObjectURL(file)} alt="selected" className="max-h-56 rounded-xl" /> : <Icon name="camera" className="h-14 w-14" />}
              <span className="text-lg font-semibold">{file ? 'Photo ready. Tap to change it' : 'Take or choose a photo'}</span>
              <span className="text-sm text-slate-500">{file ? file.name : 'A clear photo in daylight works best'}</span>
            </label>
            <div>
              <label className="mb-1 block text-base font-medium text-ink">Anything else to tell us? <span className="font-normal text-slate-400">(optional)</span></label>
              <textarea className={`${input} w-full text-base`} rows={2} value={msg} onChange={e => setMsg(e.target.value)} placeholder="e.g. white powder under the leaves, worms stopped eating…" />
            </div>
            <div>
              <div className="mb-1 flex items-baseline justify-between"><span className="text-base font-medium text-ink">How much is affected?</span>
                <span className="text-base font-semibold text-brand-700">{Number(pct) <= 15 ? 'A little' : Number(pct) <= 40 ? 'Some' : Number(pct) <= 70 ? 'A lot' : 'Almost all'} · {pct}%</span></div>
              <input type="range" min={5} max={100} step={5} value={pct} onChange={e => setPct(e.target.value)} className="h-8 w-full accent-brand-600" />
              <div className="flex justify-between text-xs text-slate-400"><span>A little</span><span>Almost all</span></div>
            </div>
            <button disabled={busy || (!file && !msg.trim())} className={`${btn.primary} w-full py-4 text-lg`}>{busy ? 'Sending…' : 'Send to Ariadne'}</button>
            {err && <p className="text-base text-red-600">{err}</p>}
          </form>
        </Card>
      ) : (
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
            <button disabled={busy} className={`${btn.primary} ml-auto`}>{busy ? 'Sending…' : farmer ? 'Send to Ariadne' : 'Send'}</button>
          </div>
          <div className="flex flex-wrap gap-2">{(PROMPTS[user?.role ?? ''] ?? []).map(p => (
            <button type="button" key={p} onClick={() => send(p)} className="rounded-full border border-slate-200 px-3 py-1 text-xs text-slate-600 hover:border-brand-500 hover:text-brand-700">{p}</button>))}</div>
          {err && <p className="text-sm text-red-600">{err}</p>}
        </form>
      </Card>
      )}
      <div className="mt-6 space-y-6">{thread.map((t, i) => (
        <div key={t.inc.id + '-' + i} className="space-y-3">
          <div className="flex justify-end"><div className="max-w-[80%] rounded-2xl rounded-tr-sm bg-brand-600 px-4 py-2.5 text-sm text-white">
            {t.img && <img src={t.img} alt="upload" className="mb-2 h-28 rounded-lg" />}{t.q}</div></div>
          <Card>{t.inc.status === 'running'
            ? (t.slow ? <div className="rounded-xl border border-gold-200 bg-gold-50 p-4 text-sm text-gold-700">This is taking longer than usual. Ariadne is still working in the background; check <b>Incidents</b> in a minute for the result.</div> : <Progress inc={t.inc} />)
            : <IncidentCard inc={t.inc} />}</Card>
        </div>))}</div>
    </div>
  )
}
