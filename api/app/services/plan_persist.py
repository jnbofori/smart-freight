"""Persist an OptimizeResponse onto trucks / drivers / orders."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.enums import DriverStatus, OrderStatus, TruckStatus
from app.models import Driver, Order, Truck
from app.schemas import OptimizeResponse


def persist_optimize_result(
    db: Session,
    result: OptimizeResponse,
    trucks: list[Truck],
    drivers: list[Driver],
    orders: list[Order],
    *,
    commit: bool = True,
) -> None:
    """Write assignment results; does not change OFF / OOS statuses."""
    order_by_id = {o.id: o for o in orders}
    assigned_truck_ids: set[int] = set()
    assigned_driver_ids: set[int] = set()
    for assignment in result.assignments:
        assigned_truck_ids.add(assignment.truck_id)
        if assignment.driver_id is not None:
            assigned_driver_ids.add(assignment.driver_id)
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
        elif truck.status == TruckStatus.ASSIGNED.value:
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

    if commit:
        db.commit()
