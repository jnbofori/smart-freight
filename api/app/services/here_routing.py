"""HERE Routing API v8 — truck-aware duration/distance with road polylines."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from app.config import settings
from app.services.flexpolyline import decode_flexpolyline
from app.services.geocode import LatLng

TORONTO = ZoneInfo("America/Toronto")

# key -> (minutes, meters, shape)
_cache: dict[str, tuple[float, float, list[LatLng]]] = {}


@dataclass
class RouteLeg:
    duration_min: float
    distance_m: float
    source: str  # "here" | "fallback"
    shape: list[LatLng] = field(default_factory=list)


def _hour_bucket() -> int:
    return datetime.now(tz=TORONTO).hour


def _cache_key(a: LatLng, b: LatLng) -> str:
    return (
        f"{a.lat:.4f},{a.lng:.4f}->{b.lat:.4f},{b.lng:.4f}@{_hour_bucket()}"
    )


def _section_shape(section: dict, origin: LatLng, dest: LatLng) -> list[LatLng]:
    encoded = section.get("polyline")
    if not encoded:
        return [origin, dest]
    try:
        points = decode_flexpolyline(encoded)
        if len(points) >= 2:
            return points
    except Exception:
        pass
    return [origin, dest]


def route_leg(origin: LatLng, dest: LatLng) -> RouteLeg:
    """Traffic-aware truck route when HERE key present; else empty (caller falls back)."""
    if not settings.here_live:
        return RouteLeg(duration_min=0, distance_m=0, source="fallback")

    key = _cache_key(origin, dest)
    if key in _cache:
        mins, meters, shape = _cache[key]
        return RouteLeg(
            duration_min=mins,
            distance_m=meters,
            source="here",
            shape=list(shape),
        )

    try:
        with httpx.Client(timeout=12.0) as client:
            for transport in ("truck", "car"):
                resp = client.get(
                    "https://router.hereapi.com/v8/routes",
                    params={
                        "transportMode": transport,
                        "origin": f"{origin.lat},{origin.lng}",
                        "destination": f"{dest.lat},{dest.lng}",
                        "return": "summary,travelSummary,polyline",
                        "apiKey": settings.here_api_key,
                    },
                )
                if resp.status_code >= 400:
                    continue
                data = resp.json()
                routes = data.get("routes") or []
                if not routes:
                    continue
                sections = routes[0].get("sections") or []
                if not sections:
                    continue

                total_duration_s = 0.0
                total_length_m = 0.0
                shape: list[LatLng] = []
                for section in sections:
                    summary = (
                        section.get("travelSummary")
                        or section.get("summary")
                        or {}
                    )
                    total_duration_s += float(
                        summary.get("duration") or summary.get("baseDuration") or 0
                    )
                    total_length_m += float(summary.get("length") or 0)
                    sec_pts = _section_shape(section, origin, dest)
                    if not shape:
                        shape.extend(sec_pts)
                    else:
                        # skip duplicate join point
                        shape.extend(sec_pts[1:] if sec_pts else [])

                if not shape:
                    shape = [origin, dest]

                mins = max(1.0, total_duration_s / 60.0)
                _cache[key] = (mins, total_length_m, list(shape))
                return RouteLeg(
                    duration_min=mins,
                    distance_m=total_length_m,
                    source="here",
                    shape=shape,
                )
    except Exception:
        pass
    return RouteLeg(duration_min=0, distance_m=0, source="fallback")
