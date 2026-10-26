"""Authoritative supply-chain calculations (safety stock, ROP, capacity, degradation).

Pure functions: agents and the API call these; the LLM never generates stock figures.
"""
import math
from dataclasses import asdict, dataclass
from datetime import date

from app.db.models import Entity, Inventory

Z_SERVICE_95 = 1.65


def safety_stock(daily_std: float, lead_time_days: float, z: float = Z_SERVICE_95) -> float:
    return z * daily_std * math.sqrt(max(lead_time_days, 0))


def reorder_point(daily_demand: float, lead_time_days: float, safety: float) -> float:
    return daily_demand * lead_time_days + safety


def capacity_utilisation(throughput: float, capacity: float) -> float:
    return 0.0 if capacity <= 0 else min(throughput / capacity, 1.5)


@dataclass
class StockStatus:
    product: str
    on_hand: float
    reserved: float
    available: float
    safety_stock: float
    reorder_point: float
    sellable: float
    daily_demand: float
    days_of_cover: float
    degrades_in_days: float
    unit_price: float
    is_finished: bool
    status: str  # ok | reorder | critical | degrading

    def dict(self) -> dict:
        return {k: round(v, 2) if isinstance(v, float) else v for k, v in asdict(self).items()}


def stock_status(inv: Inventory, today: date | None = None) -> StockStatus:
    today = today or date.today()
    ss = safety_stock(inv.demand_std, inv.lead_time_days)
    rop = reorder_point(inv.daily_demand, inv.lead_time_days, ss)
    available = max(inv.on_hand - inv.reserved, 0.0)
    sellable = max(available - ss, 0.0) if inv.is_finished else 0.0
    cover = available / inv.daily_demand if inv.daily_demand > 0 else float("inf")
    degrade = max(inv.shelf_life_days - (today - inv.stocked_on).days, 0.0)
    if available <= ss:
        status = "critical"
    elif available <= rop:
        status = "reorder"
    elif degrade < min(cover, 365) and degrade <= 3:
        status = "degrading"
    else:
        status = "ok"
    return StockStatus(inv.product, inv.on_hand, inv.reserved, available, ss, rop, sellable,
                       inv.daily_demand, min(cover, 999.0), degrade, inv.unit_price,
                       inv.is_finished, status)


SURPLUS_COVER_DAYS = 14  # more than this many days of sellable stock beyond what the buyers draw is surplus
MIN_SURPLUS_KG = 20.0


def surplus_qty(inv: Inventory, st: StockStatus | None = None) -> float:
    """Finished stock the owner cannot use or sell in time: it will spoil before the usual demand takes it, or it
    far exceeds what the buyers draw. Offered to other buyers by the guardian agent."""
    st = st or stock_status(inv)
    if not inv.is_finished or st.sellable <= 0:
        return 0.0
    spoils = max(st.available - inv.daily_demand * st.degrades_in_days, 0.0) if st.degrades_in_days < min(st.days_of_cover, 365) else 0.0
    excess = max(st.available - (st.reorder_point + inv.daily_demand * SURPLUS_COVER_DAYS), 0.0)
    q = min(max(spoils, excess), st.sellable)
    return round(q, 1) if q >= max(MIN_SURPLUS_KG, 0.1 * st.available) else 0.0


def entity_capacity(e: Entity) -> dict:
    util = capacity_utilisation(e.daily_throughput, e.capacity_per_day)
    return {"capacity": e.capacity_per_day, "load": e.daily_throughput, "utilisation": round(util, 3),
            "spare": round(max(e.capacity_per_day - e.daily_throughput, 0), 1), "basis": "per_day"}
