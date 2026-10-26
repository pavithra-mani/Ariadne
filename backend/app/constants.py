"""Domain constants (conversion ratios, horizon, product prices) with provenance.

Every value has a built-in default (a reviewed assumption). At startup `app.refresh.live_data` tries to replace
the ones that have a trusted public source (prices from the Central Silk Board bulletin); a value that cannot
be refreshed keeps its last good value from the database, and failing that the default. `get()` is cheap and
always safe to call: it never touches the network.
"""
import threading

# name -> (default, unit, note)
DEFAULTS: dict[str, tuple[float, str, str]] = {
    "leaf_per_kg_cocoon": (17.0, "kg leaf / kg cocoon", "assumption: no public feed; tune with a sericulture expert"),
    "cocoon_per_yarn": (9.5, "kg cocoon / kg raw silk", "assumption (FAO reeling manual range ~8-12); no public feed"),
    "yarn_per_thread": (1.05, "kg yarn / kg twisted thread", "assumption: ~5% twisting/winding waste; no public feed"),
    "horizon_days": (14.0, "days", "planning horizon for flow calculations"),
    "truck_cost_per_km": (18.0, "INR / vehicle-km", "ASSUMPTION (placeholder): replace with local transporters' rates"),
    "unmet_penalty_multiplier": (3.0, "x unit price per unmet kg", "ASSUMPTION: an unmet kg of input halts production; valued at 3x its price"),
    "accept_prior_a": (2.0, "pseudo-count", "Beta prior on a vendor accepting an offer: a successes ..."),
    "accept_prior_b": (1.0, "pseudo-count", "... and b declines (prior mean 0.67)"),
    "price_leaves": (4.0, "INR/kg", "default: no public price feed for mulberry leaf"),
    "price_cocoon": (480.0, "INR/kg", "default; live: CSB reeling-cocoon prices, Karnataka markets"),
    "price_yarn": (4800.0, "INR/kg", "default; live: CSB raw-silk (filature) price"),
    "price_thread": (5600.0, "INR/kg", "default; live: CSB multi-end raw-silk price"),
}
PRICE_OF = {"leaves": "price_leaves", "cocoon": "price_cocoon", "yarn": "price_yarn", "thread": "price_thread"}

_cache: dict[str, float] = {}
_lock = threading.Lock()


def get(name: str) -> float:
    with _lock:
        if name in _cache:
            return _cache[name]
    return DEFAULTS[name][0]


def price(product: str) -> float:
    return get(PRICE_OF[product])


def set_cache(values: dict[str, float]) -> None:
    with _lock:
        _cache.clear()
        _cache.update(values)


def load_from_db() -> None:
    """Prime the in-memory cache from the stored (last good) values."""
    from app.db.models import Constant
    from app.db.session import session_scope
    with session_scope() as db:
        set_cache({c.name: c.value for c in db.query(Constant) if c.name in DEFAULTS})


def snapshot() -> list[dict]:
    """Every constant with its current value, source and freshness (for the System page)."""
    from app.db.models import Constant
    from app.db.session import session_scope
    with session_scope() as db:
        stored = {c.name: c for c in db.query(Constant)}
    out = []
    for name, (default, unit, note) in DEFAULTS.items():
        row = stored.get(name)
        out.append({"name": name, "value": row.value if row else default, "unit": unit, "default": default,
                    "source": row.source if row else "built-in default", "source_url": row.source_url if row else "",
                    "live": bool(row and row.is_live), "fetched_at": row.fetched_at if row else None, "note": note})
    return out
