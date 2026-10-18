"""Append-only per-truck route history."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from sqlalchemy.orm import Session

from app.enums import OrderStatus
from app.models import Driver, Order, RouteHistoryEntry, Truck
from app.schemas import OptimizeResponse, TruckAssignment

_MAX_ENTRIES_PER_TRUCK = 50


def snapshot_from_assignment(a: TruckAssignment) -> dict[str, Any]:
    stops: list[dict[str, Any]] = []
    if a.route and a.route.stops:
        for s in a.route.stops:
            stops.append(
                {
                    "seq": s.seq,
                    "ordno": s.ordno,
                    "destination": s.destination_address or s.destination_city,
                    "eta_min": round(float(s.eta_min), 1),
                }
            )
    else:
        for i, ordno in enumerate(a.order_ordnos):
            dest = a.destinations[i] if i < len(a.destinations) else ""
            stops.append(
                {
                    "seq": i,
                    "ordno": ordno,
                    "destination": dest,
                    "eta_min": 0,
                }
            )
    return {
        "truck_id": a.truck_id,
        "unit_number": a.unit_number,
        "driver_name": a.driver_name or "",
        "driver_code": a.driver_code or "",
        "order_ordnos": list(a.order_ordnos),
        "destinations": list(a.destinations),
        "corridor": (a.route.corridor if a.route else "") or "",
        "reasoning_summary": a.reasoning_summary or "",
        "stops": stops,
    }


def _assignment_snapshots_from_db(
    db: Session,
    *,
    truck_ids: set[int] | None = None,
) -> list[dict[str, Any]]:
    trucks = {t.id: t for t in db.query(Truck).all()}
    drivers = {d.id: d for d in db.query(Driver).all()}
    assigned = (
        db.query(Order)
        .filter(Order.status == OrderStatus.ASSIGNED.value)
        .all()
    )
    by_truck: dict[int, list[Order]] = defaultdict(list)
    for order in assigned:
        if order.assigned_truck_id is None:
            continue
        if truck_ids is not None and order.assigned_truck_id not in truck_ids:
            continue
        by_truck[order.assigned_truck_id].append(order)

    # Include requested trucks even if they now have zero stops (route cleared)
    if truck_ids is not None:
        for tid in truck_ids:
            by_truck.setdefault(tid, [])

    out: list[dict[str, Any]] = []
    for truck_id, group in sorted(by_truck.items(), key=lambda item: item[0]):
        truck = trucks.get(truck_id)
        if truck is None:
            continue
        ordered = sorted(
            group,
            key=lambda o: (
                o.stop_seq is None,
                o.stop_seq if o.stop_seq is not None else 0,
                o.ordno,
            ),
        )
        driver = None
        if ordered and ordered[0].assigned_driver_id is not None:
            driver = drivers.get(ordered[0].assigned_driver_id)
        if driver is None:
            for d in drivers.values():
                if d.truck_id == truck_id:
                    driver = d
                    break
        destinations = sorted(
            {
                (o.destination_address or "").strip() or o.destination_city
                for o in ordered
            }
        )
        stops = [
            {
                "seq": i if o.stop_seq is None else int(o.stop_seq),
                "ordno": o.ordno,
                "destination": (o.destination_address or "").strip()
                or o.destination_city,
                "eta_min": 0,
            }
            for i, o in enumerate(ordered)
        ]
        out.append(
            {
                "truck_id": truck.id,
                "unit_number": truck.unit_number,
                "driver_name": driver.name if driver else "",
                "driver_code": driver.code if driver else "",
                "order_ordnos": [o.ordno for o in ordered],
                "destinations": destinations,
                "corridor": "",
                "reasoning_summary": (truck.reasoning_summary or "").strip(),
                "stops": stops,
            }
        )
    return out


def _trim_truck_history(db: Session, truck_id: int) -> None:
    ids = [
        row.id
        for row in db.query(RouteHistoryEntry.id)
        .filter(RouteHistoryEntry.truck_id == truck_id)
        .order_by(RouteHistoryEntry.id.desc())
        .offset(_MAX_ENTRIES_PER_TRUCK)
        .all()
    ]
    if ids:
        db.query(RouteHistoryEntry).filter(RouteHistoryEntry.id.in_(ids)).delete(
            synchronize_session=False
        )


def record_plan_history(
    db: Session,
    event_type: str,
    note: str = "",
    result: OptimizeResponse | None = None,
    *,
    assignments: list[TruckAssignment] | None = None,
    truck_ids: set[int] | list[int] | None = None,
    commit: bool = False,
) -> list[RouteHistoryEntry]:
    """Insert one history row per affected truck route.

    Prefer ``assignments`` (rebuilt tours from dispatch/breakdown/cancel) or a full
    ``result`` over a live DB scan so newly assigned orders are included.
    """
    wanted = set(truck_ids) if truck_ids is not None else None
    snapshots: list[dict[str, Any]]
    if assignments is not None:
        snapshots = []
        for a in assignments:
            if wanted is not None and a.truck_id not in wanted:
                continue
            snapshots.append(snapshot_from_assignment(a))
        if wanted is not None:
            present = {s["truck_id"] for s in snapshots}
            missing = wanted - present
            if missing:
                snapshots.extend(
                    _assignment_snapshots_from_db(db, truck_ids=missing)
                )
    elif result is not None:
        snapshots = []
        for a in result.assignments:
            if wanted is not None and a.truck_id not in wanted:
                continue
            snapshots.append(snapshot_from_assignment(a))
        # Trucks that lost all work in a full replan (wanted but not in assignments)
        if wanted is not None:
            present = {s["truck_id"] for s in snapshots}
            missing = wanted - present
            if missing:
                snapshots.extend(
                    _assignment_snapshots_from_db(db, truck_ids=missing)
                )
    else:
        snapshots = _assignment_snapshots_from_db(db, truck_ids=wanted)

    entries: list[RouteHistoryEntry] = []
    for snap in snapshots:
        entry = RouteHistoryEntry(
            event_type=event_type,
            note=(note or "")[:255],
            truck_id=int(snap["truck_id"]),
            unit_number=str(snap.get("unit_number") or ""),
            snapshot_json=json.dumps(snap, ensure_ascii=False),
        )
        db.add(entry)
        entries.append(entry)
    db.flush()
    touched = {e.truck_id for e in entries}
    for tid in touched:
        _trim_truck_history(db, tid)
    if commit:
        db.commit()
        for e in entries:
            db.refresh(e)
    return entries


def clear_plan_history(db: Session) -> None:
    db.query(RouteHistoryEntry).delete(synchronize_session=False)


def parse_route_snapshot(entry: RouteHistoryEntry) -> dict[str, Any]:
    try:
        data = json.loads(entry.snapshot_json or "{}")
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def list_route_history(
    db: Session,
    *,
    truck_id: int | None = None,
    unit_number: str | None = None,
    limit: int = 50,
) -> list[RouteHistoryEntry]:
    q = db.query(RouteHistoryEntry)
    if truck_id is not None:
        q = q.filter(RouteHistoryEntry.truck_id == truck_id)
    elif unit_number:
        q = q.filter(RouteHistoryEntry.unit_number == unit_number)
    else:
        return []
    return (
        q.order_by(RouteHistoryEntry.id.desc())
        .limit(max(1, min(limit, _MAX_ENTRIES_PER_TRUCK)))
        .all()
    )
