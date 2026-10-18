"""Place geocoding with GTA city seed cache and optional HERE lookup."""

from __future__ import annotations

import math
from dataclasses import dataclass

import httpx

from app.config import settings

# Approximate city centers for demo (Ontario / GTA) — fallback when no HERE key.
_CITY_COORDS: dict[str, tuple[float, float]] = {
    "toronto": (43.6532, -79.3832),
    "scarborough": (43.7764, -79.2318),
    "markham": (43.8561, -79.3370),
    "mississauga": (43.5890, -79.6441),
    "brampton": (43.7315, -79.7624),
    "pickering": (43.8384, -79.0868),
    "concord": (43.7970, -79.4830),
    "woodbridge": (43.7830, -79.5980),
    "newmarket": (44.0592, -79.4613),
    "hamilton": (43.2557, -79.8711),
    "milton": (43.5183, -79.8774),
    "guelph": (43.5448, -80.2482),
    "windsor": (42.3149, -83.0364),
    "london": (42.9849, -81.2453),
    "barrie": (44.3894, -79.6903),
    "richmond hill": (43.8828, -79.4403),
}


@dataclass(frozen=True)
class LatLng:
    lat: float
    lng: float


def _norm(place: str) -> str:
    return (place or "").strip().lower()


def _city_key_from_place(place: str) -> str | None:
    """If place is a bare city or ends with a known city name, return city key."""
    key = _norm(place)
    if key in _CITY_COORDS:
        return key
    # "123 Main St, Scarborough, ON" → try last comma segments
    for part in reversed([p.strip() for p in key.replace(", ontario", "").replace(", canada", "").split(",")]):
        if part in _CITY_COORDS:
            return part
        # strip trailing " on"
        if part.endswith(" on"):
            cand = part[:-3].strip()
            if cand in _CITY_COORDS:
                return cand
    return None


# Process-lifetime geocode cache (HERE + city fallbacks)
_geo_cache: dict[str, LatLng | None] = {}


def geocode_place_sync(place: str) -> LatLng | None:
    """Geocode a street address or city. Prefers HERE when live; else city center cache."""
    key = _norm(place)
    if not key:
        return None
    if key in _geo_cache:
        return _geo_cache[key]

    result: LatLng | None = None
    if settings.here_live:
        try:
            with httpx.Client(timeout=8.0) as client:
                q = place if "," in place or any(ch.isdigit() for ch in place) else f"{place}, Ontario, Canada"
                if "canada" not in _norm(q) and "on" not in _norm(q).split(",")[-1]:
                    q = f"{q}, Ontario, Canada"
                resp = client.get(
                    "https://geocode.search.hereapi.com/v1/geocode",
                    params={
                        "q": q,
                        "apiKey": settings.here_api_key,
                        "limit": 1,
                        "in": "countryCode:CAN",
                    },
                )
                resp.raise_for_status()
                items = resp.json().get("items") or []
                if items:
                    pos = items[0]["position"]
                    result = LatLng(lat=float(pos["lat"]), lng=float(pos["lng"]))
        except Exception:
            pass

    if result is None:
        city = _city_key_from_place(place)
        if city and city in _CITY_COORDS:
            lat, lng = _CITY_COORDS[city]
            result = LatLng(lat=lat, lng=lng)

    _geo_cache[key] = result
    return result


def geocode_city_sync(city: str) -> LatLng | None:
    """Backward-compatible city geocode."""
    return geocode_place_sync(city)


def bearing_degrees(origin: LatLng, dest: LatLng) -> float:
    """Initial bearing from origin to dest in degrees [0, 360)."""
    lat1 = math.radians(origin.lat)
    lat2 = math.radians(dest.lat)
    dlon = math.radians(dest.lng - origin.lng)
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    brng = math.degrees(math.atan2(x, y))
    return (brng + 360.0) % 360.0


def corridor_label(bearing: float) -> str:
    """Coarse 8-way corridor from bearing."""
    dirs = [
        (22.5, "north"),
        (67.5, "northeast"),
        (112.5, "east"),
        (157.5, "southeast"),
        (202.5, "south"),
        (247.5, "southwest"),
        (292.5, "west"),
        (337.5, "northwest"),
        (360.0, "north"),
    ]
    for limit, name in dirs:
        if bearing < limit:
            return name
    return "north"


def corridor_affinity(a: str, b: str) -> float:
    """Score 0–1 how similar two corridor labels are."""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    order = [
        "north",
        "northeast",
        "east",
        "southeast",
        "south",
        "southwest",
        "west",
        "northwest",
    ]
    try:
        ia, ib = order.index(a), order.index(b)
    except ValueError:
        return 0.2 if a[:1] == b[:1] else 0.0
    diff = min(abs(ia - ib), 8 - abs(ia - ib))
    if diff == 1:
        return 0.6
    if diff == 2:
        return 0.25
    return 0.0


def place_corridor(place: str, depot_place: str = "toronto") -> str:
    depot = geocode_place_sync(depot_place) or LatLng(43.6532, -79.3832)
    dest = geocode_place_sync(place)
    if dest is None:
        return "unknown"
    return corridor_label(bearing_degrees(depot, dest))


def city_corridor(city: str, depot_city: str = "toronto") -> str:
    return place_corridor(city, depot_city)
