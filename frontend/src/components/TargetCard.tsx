import { useState } from 'react'
import { Link } from 'react-router-dom'
import { post } from '../api'
import { Card, btn, input } from './ui'

/** Spinners say how much yarn they want; reelers say how much extra yarn is being ordered. Ariadne then checks every tier by itself. */
export default function TargetCard({ role, onDone }: { role: 'reeler' | 'spinner'; onDone?: () => void }) {
  const [qty, setQty] = useState('')
  const [hz, setHz] = useState('14')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')
  const spinner = role === 'spinner'
  const go = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!qty) return
    setBusy(true); setErr(''); setMsg('')
    try {
      await post('/api/target', { target_qty: Number(qty), horizon_days: Number(hz) || 14 })
      setMsg('Saved. Ariadne is checking the whole chain…')
      setQty('')
      onDone?.(); setTimeout(() => onDone?.(), 4000); setTimeout(() => onDone?.(), 10000)
    } catch (x: any) { setErr(x.message) } finally { setBusy(false) }
  }
  return (
    <Card className="mb-8" title={spinner ? 'Add demand: yarn I want' : 'Add demand: extra yarn orders'}
      subtitle="Ariadne checks every tier, from reelers down to mulberry farms, and sends offers to other suppliers by itself. You will be asked to approve each deal.">
      <form onSubmit={go} className="flex flex-wrap items-center gap-2">
        <input className={`${input} w-40`} type="number" min={1} placeholder={spinner ? 'yarn wanted (kg)' : 'extra yarn (kg)'} value={qty} onChange={e => setQty(e.target.value)} />
        <span className="text-sm text-slate-500">within</span>
        <input className={`${input} w-20`} type="number" min={1} max={180} value={hz} onChange={e => setHz(e.target.value)} /><span className="text-sm text-slate-500">days</span>
        <button disabled={busy || !qty} className={btn.primary}>{busy ? 'Saving…' : 'Set demand'}</button>
        <Link to="/chain" className="text-sm font-medium text-brand-600 hover:underline">See the whole chain →</Link>
      </form>
      {msg && <p className="mt-3 rounded-lg bg-brand-50 px-3 py-2 text-sm text-brand-700">{msg}</p>}
      {err && <p className="mt-2 text-sm text-red-600">{err}</p>}
    </Card>
  )
}
