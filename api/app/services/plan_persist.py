"""Persist an OptimizeResponse onto trucks / drivers / orders."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.enums import DriverStatus, OrderStatus, TruckStatus
from app.models import Driver, Order, PlanMeta, Truck
from app.schemas import OptimizeResponse
from app.services.plan_history import clear_plan_history, record_plan_history

_PLAN_META_ID = 1


def _upsert_plan_meta(db: Session, unassigned_summary: str) -> None:
    meta = db.get(PlanMeta, _PLAN_META_ID)
    if meta is None:
        meta = PlanMeta(id=_PLAN_META_ID, unassigned_summary=unassigned_summary or "")
        db.add(meta)
    else:
        meta.unassigned_summary = unassigned_summary or ""


def clear_plan_summaries(db: Session) -> None:
    """Clear persisted LLM / fallback briefings (e.g. on reset)."""
    for truck in db.query(Truck).all():
        truck.reasoning_summary = ""
    meta = db.get(PlanMeta, _PLAN_META_ID)
    if meta is not None:
        meta.unassigned_summary = ""
    clear_plan_history(db)


def persist_optimize_result(
    db: Session,
    result: OptimizeResponse,
    trucks: list[Truck],
    drivers: list[Driver],
    orders: list[Order],
    *,
    commit: bool = True,
    event_type: str = "optimize",
    history_note: str = "",
) -> None:
    """Write assignment results; does not change OFF / OOS statuses."""
    order_by_id = {o.id: o for o in orders}
    truck_by_id = {t.id: t for t in trucks}
    assigned_truck_ids: set[int] = set()
    assigned_driver_ids: set[int] = set()
    for assignment in result.assignments:
        assigned_truck_ids.add(assignment.truck_id)
        if assignment.driver_id is not None:
            assigned_driver_ids.add(assignment.driver_id)
        truck = truck_by_id.get(assignment.truck_id)
        if truck is not None:
            truck.reasoning_summary = assignment.reasoning_summary or ""
        seq_by_order: dict[int, int] = {}
        if assignment.route and assignment.route.stops:
            for stop in assignment.route.stops:
                seq_by_order[stop.order_id] = stop.seq
        else:
            for i, order_id in enumerate(assignment.order_ids):
                seq_by_order[order_id] = i
        for order_id in assignment.order_ids:
            order = order_by_id.get(order_id)
            if order is None:
                continue
            order.assigned_truck_id = assignment.truck_id
            order.assigned_driver_id = assignment.driver_id
            order.status = OrderStatus.ASSIGNED.value
            order.stop_seq = seq_by_order.get(order_id, 0)

    for truck in trucks:
        if truck.id in assigned_truck_ids:
            if truck.status != TruckStatus.OUT_OF_SERVICE.value:
                truck.status = TruckStatus.ASSIGNED.value
        else:
            truck.reasoning_summary = ""
            if truck.status == TruckStatus.ASSIGNED.value:
                truck.status = TruckStatus.AVAILABLE.value

    for driver in drivers:
        if driver.id in assigned_driver_ids:
            if driver.status not in {
                DriverStatus.OFF.value,
                DriverStatus.OUT_OF_SERVICE.value,
            }:
                driver.status = DriverStatus.ASSIGNED.value
        elif driver.status == DriverStatus.ASSIGNED.value:
            driver.status = DriverStatus.AVAILABLE.value

    _upsert_plan_meta(db, result.unassigned_summary or "")

    note = history_note
    if not note:
        assigned = int(result.summary.get("orders_assigned", 0)) if result.summary else 0
        unassigned = int(result.summary.get("orders_unassigned", 0)) if result.summary else 0
        note = f"{assigned} assigned, {unassigned} unassigned"
    record_plan_history(db, event_type, note, result, commit=False)

    if commit:
        db.commit()
