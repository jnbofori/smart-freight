"""Open-Meteo weather padding for travel legs (no API key)."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.services.geocode import LatLng


@dataclass
class WeatherPad:
    delay_factor: float  # multiply travel minutes
    note: str


# Rounded lat/lng → pad (process lifetime; weather changes slowly for demo)
_cache: dict[str, WeatherPad] = {}


def _cache_key(point: LatLng) -> str:
    # ~1 km cells — enough for delay factor, avoids near-duplicate fetches
    return f"{point.lat:.2f},{point.lng:.2f}"


def weather_pad_for_point(point: LatLng) -> WeatherPad:
    """Fetch current/near-term conditions; return a delay factor + note."""
    key = _cache_key(point)
    if key in _cache:
        return _cache[key]

    pad = WeatherPad(delay_factor=1.0, note="")
    try:
        with httpx.Client(timeout=6.0) as client:
            resp = client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": point.lat,
                    "longitude": point.lng,
                    "current": "precipitation,weather_code,wind_speed_10m",
                    "timezone": "America/Toronto",
                },
            )
            resp.raise_for_status()
            cur = resp.json().get("current") or {}
            precip = float(cur.get("precipitation") or 0)
            wind = float(cur.get("wind_speed_10m") or 0)
            code = int(cur.get("weather_code") or 0)

            factor = 1.0
            notes: list[str] = []
            # WMO codes: 61+ rain, 71+ snow, 95+ thunderstorm
            if code >= 95:
                factor = max(factor, 1.25)
                notes.append("thunderstorm risk")
            elif code >= 71:
                factor = max(factor, 1.2)
                notes.append("snow/ice risk")
            elif code >= 61 or precip >= 1.0:
                factor = max(factor, 1.12)
                notes.append("rain")
            if wind >= 50:
                factor = max(factor, 1.15)
                notes.append("high wind")
            elif wind >= 35:
                factor = max(factor, 1.05)
                notes.append("gusty")

            if notes:
                pad = WeatherPad(delay_factor=factor, note=", ".join(notes))
    except Exception:
        pass

    _cache[key] = pad
    return pad


def weather_pad_midpoint(a: LatLng, b: LatLng) -> WeatherPad:
    mid = LatLng(lat=(a.lat + b.lat) / 2.0, lng=(a.lng + b.lng) / 2.0)
    return weather_pad_for_point(mid)
