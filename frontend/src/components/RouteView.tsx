export default function RouteView({ route }: { route: any }) {
  if (!route?.routes?.length) return null
  const mins = (m: number) => `${Math.floor(m / 60)}h ${m % 60}m`
  return (
    <div className="rounded-xl bg-slate-50 p-3 text-xs text-slate-600">
      <div className="mb-1.5 font-medium text-slate-700">Route · {route.distance_km} km · {mins(route.duration_min)} · found in search {route.search_attempt} (within {route.radius_km} km)</div>
      {route.routes.map((r: any) => (
        <div key={r.vehicle} className="flex flex-wrap items-center gap-1.5 py-0.5">
          <span className="rounded bg-white px-1.5 py-0.5 ring-1 ring-slate-200">Truck {r.vehicle} · {r.load_kg} kg</span>
          <span className="text-slate-400">{route.depot}</span>
          {r.stops.map((s: any) => <span key={s.entity_id + '-' + s.arrive_min} className="flex items-center gap-1.5"><span className="text-slate-300">→</span><span>{s.name} <span className="text-slate-400">({s.qty} kg)</span></span></span>)}
          <span className="text-slate-300">→</span><span className="font-medium">delivery</span>
        </div>))}
    </div>
  )
}
