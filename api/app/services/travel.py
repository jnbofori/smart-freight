"""Prototype travel times and service-level due windows (Toronto-local minutes)."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.enums import DEFAULT_TRAVEL_MIN, DEPOT_READY_MIN, SERVICE_TIME_MIN, OrderService

TORONTO = ZoneInfo("America/Toronto")

# Undirected GTA drive minutes (symmetric lookup).
_CITY_TRAVEL: dict[frozenset[str], int] = {
    frozenset({"toronto", "scarborough"}): 25,
    frozenset({"toronto", "markham"}): 35,
    frozenset({"toronto", "mississauga"}): 35,
    frozenset({"toronto", "brampton"}): 45,
    frozenset({"toronto", "pickering"}): 35,
    frozenset({"toronto", "concord"}): 30,
    frozenset({"toronto", "woodbridge"}): 35,
    frozenset({"scarborough", "markham"}): 20,
    frozenset({"scarborough", "pickering"}): 20,
    frozenset({"scarborough", "newmarket"}): 45,
    frozenset({"mississauga", "brampton"}): 20,
    frozenset({"mississauga", "hamilton"}): 40,
    frozenset({"mississauga", "milton"}): 25,
    frozenset({"brampton", "guelph"}): 45,
    frozenset({"brampton", "windsor"}): 180,
    frozenset({"pickering", "london"}): 150,
    frozenset({"milton", "barrie"}): 75,
    frozenset({"richmond hill", "markham"}): 15,
    frozenset({"woodbridge", "concord"}): 15,
}


def _norm(city: str) -> str:
    return (city or "").strip().lower()


def travel_minutes(from_city: str, to_city: str) -> int:
    a, b = _norm(from_city), _norm(to_city)
    if not a or not b or a == b:
        return 10
    return _CITY_TRAVEL.get(frozenset({a, b}), DEFAULT_TRAVEL_MIN)


def service_minutes() -> int:
    return SERVICE_TIME_MIN


def planning_day_start(planning_date: date) -> datetime:
    return datetime.combine(planning_date, time(0, 0), tzinfo=TORONTO)


def minutes_on_day(planning_date: date, minute_of_day: int) -> datetime:
    return planning_day_start(planning_date) + timedelta(minutes=minute_of_day)


def datetime_to_day_minutes(dt: datetime, planning_date: date) -> int:
    local = dt.astimezone(TORONTO) if dt.tzinfo else dt.replace(tzinfo=TORONTO)
    if local.date() != planning_date:
        # Multi-day: clamp to end of planning day for single-day prototype
        if local.date() > planning_date:
            return 24 * 60 - 1
        return 0
    return local.hour * 60 + local.minute


def effective_window_end_min(
    *,
    planning_date: date,
    service: str,
    appointment: bool,
    delivery_window_start: datetime | None,
    delivery_window_end: datetime | None,
    driver_shift_end_min: int,
) -> tuple[int | None, bool]:
    """
    Return (due_end_min, hard).
    hard=True means miss is a reject; hard=False is soft preference only.
    """
    if delivery_window_end is not None:
        end_min = datetime_to_day_minutes(delivery_window_end, planning_date)
        return end_min, True  # explicit window is a hard constraint

    if delivery_window_start is not None and appointment:
        # Appointment flagged but only start known — prefer early (soft)
        return driver_shift_end_min, False

    svc = (service or "").upper()
    if svc in {OrderService.RUSH.value, OrderService.SAME_DAY.value, "RUSH90", "90 MINUTES"}:
        return 15 * 60, True  # 15:00 hard for rush family
    if svc == OrderService.OVERNIGHT.value:
        # Single-day plan: prefer early (soft), due mid-morning preference
        return 12 * 60, False
    if svc == OrderService.EXPEDITE.value:
        return 14 * 60, True

    # Open until driver shift end (soft)
    return driver_shift_end_min, False


def effective_window_start_min(
    *,
    planning_date: date,
    delivery_window_start: datetime | None,
    driver_shift_start_min: int,
) -> int:
    if delivery_window_start is None:
        return max(driver_shift_start_min, DEPOT_READY_MIN)
    start = datetime_to_day_minutes(delivery_window_start, planning_date)
    return max(start, driver_shift_start_min, DEPOT_READY_MIN)


def utc_now_naive_fallback() -> date:
    return datetime.now(tz=TORONTO).date()
