"""Refresh prices from trusted public sources, with fallback.

Source: Central Silk Board (Ministry of Textiles, Govt. of India) silk-price bulletin
  * reeling cocoon prices by Karnataka market  -> price_cocoon (mean of the markets' cross-breed average)
  * raw silk prices (filature 20/22, multi-end) -> price_yarn, price_thread
Rules: one polite GET per page, identified User-Agent, at most once per STALE_HOURS; every value is sanity-checked
against a plausible range; on any failure (network, layout change, out-of-range) the last good stored value is kept,
and without one the built-in default stays in force. Nothing here can crash the app.
"""
import html
import logging
import re
import threading
from datetime import datetime, timedelta

import httpx

from app import constants
from app.db.models import AuditLog, Constant, Inventory
from app.db.session import session_scope

log = logging.getLogger("ariadne.live_data")
BASE = "https://csb.gov.in/statistics/silk-bulletin"
COCOON_URL = f"{BASE}/reeling-cocoons-prices"
RAW_SILK_URL = f"{BASE}/raw-silk-prices-of-karnataka-tamilnadu-andhra-pradesh"
UA = "AriadneBot/1.0 (student supply-chain project; daily price refresh; contact: team14)"
STALE_HOURS = 6
RANGE = {"price_cocoon": (150, 1500), "price_yarn": (2000, 15000), "price_thread": (2500, 20000)}


def _rows(page: str) -> list[list[str]]:
    page = re.sub(r"<(script|style)[\s\S]*?</\1>", "", page)
    out = []
    for r in re.findall(r"<tr[\s\S]*?</tr>", page):
        cells = [html.unescape(re.sub(r"<[^>]+>", "", c)).replace("\xa0", " ").strip()
                 for c in re.findall(r"<t[hd][\s\S]*?</t[hd]>", r)]
        if cells:
            out.append(cells)
    return out


def _num(x: str) -> float | None:
    x = x.replace(",", "").strip()
    return float(x) if re.fullmatch(r"\d+(\.\d+)?", x) else None


def parse_cocoon(page: str) -> tuple[float, str] | None:
    avgs = []
    for r in _rows(page):
        if len(r) >= 5 and r[0].isdigit() and (v := _num(r[4])):
            avgs.append(v)
    return (round(sum(avgs) / len(avgs), 1), f"mean of {len(avgs)} Karnataka markets (cross breed, avg)") if avgs else None


def parse_raw_silk(page: str) -> dict[str, tuple[float, str]]:
    out = {}
    for r in _rows(page):
        if r and r[0].strip() == "20/22" and len(r) >= 4 and (v := _num(r[3])):
            out["price_yarn"] = (v, "filature 20/22 avg")
        if r and r[0].lower().startswith("multiend") and len(r) >= 5 and (v := _num(r[4])):
            out["price_thread"] = (v, f"multi-end silk avg ({r[1]})")
    return out


def _get(url: str) -> str:
    r = httpx.get(url, headers={"User-Agent": UA}, timeout=12, follow_redirects=True)
    r.raise_for_status()
    return r.text


def _fresh(db, names: list[str]) -> bool:
    cut = datetime.utcnow() - timedelta(hours=STALE_HOURS)
    rows = [db.get(Constant, n) for n in names]
    return all(r and r.is_live and r.fetched_at and r.fetched_at > cut for r in rows)


def refresh(force: bool = False) -> dict:
    """Try each live source; returns {name: 'updated|unchanged|kept (reason)'} for the System page."""
    report: dict[str, str] = {}
    live: dict[str, tuple[float, str, str]] = {}  # name -> (value, how, url)
    with session_scope() as db:
        skip = not force and _fresh(db, list(RANGE))
    if skip:
        constants.load_from_db()
        return {n: "fresh (checked recently)" for n in RANGE}
    for url, parser, names in ((COCOON_URL, lambda p: {"price_cocoon": parse_cocoon(p)}, ["price_cocoon"]),
                               (RAW_SILK_URL, parse_raw_silk, ["price_yarn", "price_thread"])):
        try:
            got = parser(_get(url))
        except Exception as exc:
            for n in names:
                report[n] = f"kept last good value ({type(exc).__name__})"
            continue
        for n in names:
            v = got.get(n)
            if not v:
                report[n] = "kept last good value (not found on page)"
            elif not RANGE[n][0] <= v[0] <= RANGE[n][1]:
                report[n] = f"kept last good value (rejected {v[0]}: out of plausible range)"
            else:
                live[n] = (v[0], v[1], url)
    changed = []
    with session_scope() as db:
        for n, (val, how, url) in live.items():
            row = db.get(Constant, n)
            old = row.value if row else constants.DEFAULTS[n][0]
            if row is None:
                row = Constant(name=n, value=val)
                db.add(row)
            row.value, row.source, row.source_url, row.is_live, row.fetched_at = val, f"Central Silk Board - {how}", url, True, datetime.utcnow()
            report[n] = "unchanged" if abs(old - val) < 0.005 else f"updated {old:g} -> {val:g}"
            if abs(old - val) >= 0.005:
                changed.append(n)
                product = n.removeprefix("price_")
                db.query(Inventory).filter(Inventory.product == product).update({"unit_price": val})
        if changed:
            db.add(AuditLog(actor="system", action="live_prices_updated", ref=",".join(changed), details=report))
    constants.load_from_db()
    log.info("live data refresh: %s", report)
    return report


def start_background(period_hours: float = 24.0) -> None:
    """Refresh now (off the request path) and then every `period_hours` while the app runs."""
    def run():
        try:
            refresh()
        except Exception:
            log.exception("live data refresh failed")
        t = threading.Timer(period_hours * 3600, run)
        t.daemon = True
        t.start()
    threading.Thread(target=run, daemon=True, name="live-data").start()
