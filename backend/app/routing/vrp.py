"""Google OR-Tools vehicle routing for pickups (upstream) / deliveries (downstream).

Nodes: 0 = start depot, 1..n = stops, n+1 = end. Capacity and a perishability time limit are hard
constraints; stops that cannot be served are dropped (penalised disjunction) and reported, which
is what lets the recovery loop widen the search instead of returning an infeasible plan.
"""
import math
from dataclasses import dataclass

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from app.config import settings
from app.routing.provider import matrix, travel_minutes

MAX_TRANSIT_HOURS = {"leaves": 5.0, "cocoon": 8.0, "yarn": 24.0, "thread": 24.0}


def cost_per_km() -> float:
    from app import constants
    return constants.get("truck_cost_per_km")  # INR per vehicle-km: an assumption, see constants.py


@dataclass
class Stop:
    key: int           # entity id
    name: str
    lat: float
    lon: float
    qty: float


def plan_route(start: tuple[float, float], end: tuple[float, float], stops: list[Stop], product: str) -> dict:
    cap = settings.vehicle_capacity_kg
    if not stops:
        return {"routes": [], "dropped": [], "served": {}, "total_km": 0.0, "total_min": 0, "cost": 0.0, "feasible": True}
    # split stops larger than one vehicle into several visits
    visits: list[Stop] = []
    for s in stops:
        left = s.qty
        while left > 1e-6:
            q = min(left, cap)
            visits.append(Stop(s.key, s.name, s.lat, s.lon, q))
            left -= q
    n = len(visits)
    pts = [start] + [(v.lat, v.lon) for v in visits] + [end]
    dist = matrix(pts)
    d_m = [[int(x * 1000) for x in row] for row in dist]
    t_min = [[int(round(travel_minutes(x))) for x in row] for row in dist]
    demand = [0] + [int(math.ceil(v.qty)) for v in visits] + [0]
    n_vehicles = min(max(math.ceil(sum(demand) / cap), 1), settings.max_vehicles)
    max_min = int(MAX_TRANSIT_HOURS.get(product, 12) * 60)

    mgr = pywrapcp.RoutingIndexManager(n + 2, n_vehicles, [0] * n_vehicles, [n + 1] * n_vehicles)
    rt = pywrapcp.RoutingModel(mgr)
    cb = rt.RegisterTransitCallback(lambda i, j: d_m[mgr.IndexToNode(i)][mgr.IndexToNode(j)])
    rt.SetArcCostEvaluatorOfAllVehicles(cb)
    dem = rt.RegisterUnaryTransitCallback(lambda i: demand[mgr.IndexToNode(i)])
    rt.AddDimensionWithVehicleCapacity(dem, 0, [cap] * n_vehicles, True, "Load")
    svc = settings.service_minutes

    def time_cb(i, j):
        a = mgr.IndexToNode(i)
        return t_min[a][mgr.IndexToNode(j)] + (svc if 0 < a <= n else 0)
    tcb = rt.RegisterTransitCallback(time_cb)
    rt.AddDimension(tcb, 0, max_min, True, "Time")
    for k in range(1, n + 1):
        rt.AddDisjunction([mgr.NodeToIndex(k)], 10_000_000)
    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.FromMilliseconds(400)
    sol = rt.SolveWithParameters(params)
    if sol is None:
        return {"routes": [], "dropped": [s.key for s in stops], "served": {}, "total_km": 0.0, "total_min": 0,
                "cost": 0.0, "feasible": False}

    time_dim = rt.GetDimensionOrDie("Time")
    routes, served, total_km, total_min = [], {}, 0.0, 0
    for v in range(n_vehicles):
        idx, seq, load, km = rt.Start(v), [], 0, 0.0
        prev = 0
        while not rt.IsEnd(idx):
            node = mgr.IndexToNode(idx)
            if 1 <= node <= n:
                vis = visits[node - 1]
                load += vis.qty
                seq.append({"entity_id": vis.key, "name": vis.name, "qty": round(vis.qty, 1),
                            "arrive_min": sol.Value(time_dim.CumulVar(idx))})
                served[vis.key] = served.get(vis.key, 0.0) + vis.qty
            km += dist[prev][node] if node != prev else 0
            prev = node
            idx = sol.Value(rt.NextVar(idx))
        km += dist[prev][n + 1]
        if seq:
            dur = sol.Value(time_dim.CumulVar(idx))
            routes.append({"vehicle": v + 1, "stops": seq, "load_kg": round(load, 1),
                           "distance_km": round(km, 1), "duration_min": dur})
            total_km += km
            total_min = max(total_min, dur)
    dropped = sorted({visits[k - 1].key for k in range(1, n + 1) if sol.Value(rt.NextVar(mgr.NodeToIndex(k))) == mgr.NodeToIndex(k)})
    served = {k: round(x, 1) for k, x in served.items()}
    return {"routes": routes, "dropped": dropped, "served": served, "total_km": round(total_km, 1),
            "total_min": total_min, "cost": round(total_km * cost_per_km(), 2), "feasible": not dropped,
            "max_transit_min": max_min}
