"""Distance/time provider. Haversine x road factor by default; swap in OSRM / Google Routes by
implementing `matrix()` with the same signature (design doc: 'Google Routes API or OpenStreetMap')."""
import math

from app.config import settings


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def road_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    return haversine_km(a[0], a[1], b[0], b[1]) * settings.road_factor


def travel_minutes(km: float) -> float:
    return km / settings.avg_speed_kmh * 60


def _osrm_matrix(points: list[tuple[float, float]]) -> list[list[float]] | None:
    """Real road distances from an OSRM server (OpenStreetMap data). None on any failure: callers fall back to haversine."""
    try:
        import httpx
        coords = ";".join(f"{lon:.5f},{lat:.5f}" for lat, lon in points)
        r = httpx.get(f"{settings.osrm_url}/table/v1/driving/{coords}", params={"annotations": "distance"}, timeout=6,
                      headers={"User-Agent": "AriadneBot/1.0 (student project)"})
        r.raise_for_status()
        d = r.json().get("distances")
        return [[(x or 0.0) / 1000.0 for x in row] for row in d] if d else None
    except Exception:
        return None


def matrix(points: list[tuple[float, float]]) -> list[list[float]]:
    """Road distance (km) between all point pairs."""
    if settings.routing_provider == "osrm" and len(points) <= 40:
        m = _osrm_matrix(points)
        if m:
            return m
    return [[0.0 if i == j else road_km(a, b) for j, b in enumerate(points)] for i, a in enumerate(points)]
