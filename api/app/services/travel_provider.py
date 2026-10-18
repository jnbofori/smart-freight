"""Injectable travel minutes: static table or HERE + Open-Meteo between places."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.config import settings
from app.services.geocode import (
    LatLng,
    bearing_degrees,
    corridor_label,
    geocode_place_sync,
)
from app.services.here_routing import route_leg
from app.services import travel as static_travel
from app.services.weather import WeatherPad, weather_pad_midpoint


@dataclass
class TravelResult:
    minutes: float
    distance_m: float
    weather_note: str = ""
    source: str = "static"  # static | here
    shape: list[LatLng] = field(default_factory=list)


def _city_label(place: str) -> str:
    """Best-effort city name for the static GTA travel table."""
    a = (place or "").strip()
    if not a:
        return ""
    if "," in a:
        city = a.split(",")[-2].strip() if a.count(",") >= 2 else a.split(",")[-1].strip()
        return city.replace(" ON", "").replace(" Ontario", "").strip()
    return a.split(",")[0].strip()


@dataclass
class TravelProvider:
    """Caches geocodes and weather notes for a planning run.

    Scoring should call ``travel(..., live=False)`` (static table, no weather HTTP).
    Final commit / map polylines use ``live=True`` (or default when mode is live).
    """

    mode: str = "static"  # static | live
    weather_notes: list[str] = field(default_factory=list)
    _geo_cache: dict[str, LatLng | None] = field(default_factory=dict)
    # (from_key, to_key, live_flag) → result for this planning run
    _travel_cache: dict[tuple[str, str, bool], TravelResult] = field(default_factory=dict)

    @classmethod
    def create(cls) -> TravelProvider:
        mode = "live" if settings.here_live else "static"
        return cls(mode=mode)

    def geocode(self, place: str) -> LatLng | None:
        key = (place or "").strip().lower()
        if key not in self._geo_cache:
            self._geo_cache[key] = geocode_place_sync(place)
        return self._geo_cache[key]

    def corridor(self, place: str, depot_place: str = "toronto") -> str:
        """Corridor label using cached geocodes (no extra HERE hits)."""
        depot = self.geocode(depot_place) or LatLng(43.6532, -79.3832)
        dest = self.geocode(place)
        if dest is None:
            return "unknown"
        return corridor_label(bearing_degrees(depot, dest))

    def _static_result(self, a: str, b: str, oa: LatLng | None, ob: LatLng | None) -> TravelResult:
        city_a, city_b = _city_label(a), _city_label(b)
        shape = [p for p in (oa, ob) if p is not None]
        if len(shape) < 2 and oa and ob:
            shape = [oa, ob]
        return TravelResult(
            minutes=float(static_travel.travel_minutes(city_a, city_b)),
            distance_m=0.0,
            source="static",
            shape=shape if len(shape) >= 2 else ([oa, ob] if oa and ob else []),
        )

    def travel(
        self,
        from_place: str,
        to_place: str,
        *,
        live: bool | None = None,
    ) -> TravelResult:
        """Return travel between places.

        ``live=False`` — static GTA table (fast scoring / 2-opt search).
        ``live=True`` — HERE + weather when configured (final ETAs / polylines).
        ``live=None`` — follow provider mode (live if HERE enabled).
        """
        use_live = self.mode == "live" if live is None else bool(live)

        a = (from_place or "").strip()
        b = (to_place or "").strip()
        cache_key = (a.lower(), b.lower(), use_live)
        if cache_key in self._travel_cache:
            cached = self._travel_cache[cache_key]
            return TravelResult(
                minutes=cached.minutes,
                distance_m=cached.distance_m,
                weather_note=cached.weather_note,
                source=cached.source,
                shape=list(cached.shape),
            )

        if not a or not b or a.lower() == b.lower():
            pt = self.geocode(a or b)
            shape = [pt, pt] if pt else []
            result = TravelResult(
                minutes=10.0,
                distance_m=5000.0,
                source="static" if not use_live else self.mode,
                shape=shape,
            )
            self._travel_cache[cache_key] = result
            return TravelResult(
                minutes=result.minutes,
                distance_m=result.distance_m,
                weather_note=result.weather_note,
                source=result.source,
                shape=list(result.shape),
            )

        oa = self.geocode(a)
        ob = self.geocode(b)

        if not use_live or oa is None or ob is None:
            result = self._static_result(a, b, oa, ob)
            self._travel_cache[cache_key] = result
            return TravelResult(
                minutes=result.minutes,
                distance_m=result.distance_m,
                weather_note=result.weather_note,
                source=result.source,
                shape=list(result.shape),
            )

        leg = route_leg(oa, ob)
        if leg.source != "here" or leg.duration_min <= 0:
            result = self._static_result(a, b, oa, ob)
            self._travel_cache[cache_key] = result
            return TravelResult(
                minutes=result.minutes,
                distance_m=result.distance_m,
                weather_note=result.weather_note,
                source=result.source,
                shape=list(result.shape),
            )

        pad: WeatherPad = weather_pad_midpoint(oa, ob)
        mins = leg.duration_min * pad.delay_factor
        if pad.note:
            note = f"{a}→{b}: {pad.note} (×{pad.delay_factor:.2f})"
            if note not in self.weather_notes:
                self.weather_notes.append(note)
        shape = leg.shape if leg.shape else [oa, ob]
        result = TravelResult(
            minutes=mins,
            distance_m=leg.distance_m,
            weather_note=pad.note,
            source="here",
            shape=shape,
        )
        self._travel_cache[cache_key] = result
        return TravelResult(
            minutes=result.minutes,
            distance_m=result.distance_m,
            weather_note=result.weather_note,
            source=result.source,
            shape=list(result.shape),
        )

    def weather_summary(self) -> str:
        if not self.weather_notes:
            return ""
        return "; ".join(self.weather_notes[:8])
