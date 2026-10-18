"""Cancel an assigned order and re-optimize the truck's remaining tour."""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.enums import DriverStatus, OrderStatus, TruckStatus
from app.models import Driver, Order, Truck
from app.schemas import CancelResponse, TruckAssignment
from app.services.optimizer import (
    _TruckLoad,
    _build_assignment,
    _build_load_for_sequence,
    _depot_place,
    _driver_for_truck,
    _enrich_load_map_path,
    _optimize_stop_order,
)
from app.services.simulate import truck_current_place
from app.services.travel import utc_now_naive_fallback
from app.services.travel_provider import TravelProvider


def _remaining_on_truck(
    truck: Truck,
    orders: list[Order],
    *,
    exclude_id: int | None = None,
) -> list[Order]:
    return [
        o
        for o in orders
        if o.assigned_truck_id == truck.id
        and o.status == OrderStatus.ASSIGNED.value
        and o.id != exclude_id
    ]


def _rebuild_remaining(
    truck: Truck,
    driver: Driver,
    remaining: list[Order],
    day: date,
    travel: TravelProvider,
) -> TruckAssignment | None:
    """Re-optimize remaining dest-only stops from the truck's current place."""
    if not remaining:
        return None

    from app.enums import MID_SHIFT_CLOCK_MIN

    start = truck_current_place(truck, driver)
    start_time = float(MID_SHIFT_CLOCK_MIN)
    pickup_ids: set[int] = set()
    depot = _depot_place(truck, driver)

    if len(remaining) >= 2:
        stub = _TruckLoad(
            truck=truck,
            driver=driver,
            orders=list(remaining),
            current_place=start,
            current_time_min=start_time,
        )
        optimized = _optimize_stop_order(
            stub,
            day,
            travel,
            depot,
            start_place=start,
            start_time_min=start_time,
            pickup_order_ids=pickup_ids,
        )
        if optimized.route_stops and len(optimized.route_stops) == len(optimized.orders):
            if travel.mode == "live":
                _enrich_load_map_path(
                    optimized,
                    travel,
                    start_place=start,
                    pickup_order_ids=pickup_ids,
                )
            if truck.current_lat is not None and truck.current_lng is not None:
                optimized.depot_lat = truck.current_lat
                optimized.depot_lng = truck.current_lng
                optimized.depot_label = start
                optimized.truck_at_start = True
            return _build_assignment(optimized)

    load = _build_load_for_sequence(
        truck,
        driver,
        list(remaining),
        day,
        travel,
        depot,
        start_place=start,
        start_time_min=start_time,
        pickup_order_ids=pickup_ids,
        live=False,
    )
    if load is None:
        return None
    if travel.mode == "live":
        _enrich_load_map_path(
            load,
            travel,
            start_place=start,
            pickup_order_ids=pickup_ids,
        )
    if truck.current_lat is not None and truck.current_lng is not None:
        load.depot_lat = truck.current_lat
        load.depot_lng = truck.current_lng
        load.depot_label = start
        load.truck_at_start = True
    return _build_assignment(load)


def cancel_order(
    db: Session,
    order_id: int,
    *,
    persist: bool = True,
) -> CancelResponse:
    travel = TravelProvider.create()
    day = utc_now_naive_fallback()

    order = db.query(Order).filter(Order.id == order_id).first()
    if order is None:
        return CancelResponse(
            cancelled_order_id=order_id,
            ordno="",
            reason="order not found",
        )
    if order.status != OrderStatus.ASSIGNED.value:
        return CancelResponse(
            cancelled_order_id=order.id,
            ordno=order.ordno,
            reason=f"order status is {order.status}; need assigned",
        )
    if order.assigned_truck_id is None:
        return CancelResponse(
            cancelled_order_id=order.id,
            ordno=order.ordno,
            reason="order has no assigned truck",
        )

    truck = db.query(Truck).filter(Truck.id == order.assigned_truck_id).first()
    if truck is None:
        return CancelResponse(
            cancelled_order_id=order.id,
            ordno=order.ordno,
            reason="assigned truck not found",
        )

    drivers = db.query(Driver).all()
    all_orders = db.query(Order).all()
    driver = _driver_for_truck(truck, drivers)
    remaining = _remaining_on_truck(truck, all_orders, exclude_id=order.id)

    truck_id = truck.id
    unit = truck.unit_number
    ordno = order.ordno

    assignment: TruckAssignment | None = None
    if remaining and driver is not None:
        assignment = _rebuild_remaining(truck, driver, remaining, day, travel)

    if persist:
        order.status = OrderStatus.CANCELLED.value
        order.assigned_truck_id = None
        order.assigned_driver_id = None
        order.stop_seq = None

        if assignment and assignment.route and assignment.route.stops:
            by_id = {o.id: o for o in remaining}
            for stop in assignment.route.stops:
                o = by_id.get(stop.order_id)
                if o is not None:
                    o.stop_seq = stop.seq
        elif remaining:
            for i, o in enumerate(remaining):
                o.stop_seq = i

        if not remaining:
            if truck.status != TruckStatus.OUT_OF_SERVICE.value:
                truck.status = TruckStatus.AVAILABLE.value
            if driver is not None and driver.status not in {
                DriverStatus.OFF.value,
                DriverStatus.OUT_OF_SERVICE.value,
            }:
                driver.status = DriverStatus.AVAILABLE.value

        db.commit()

    if not remaining:
        released = persist and truck.status == TruckStatus.AVAILABLE.value
        reason = (
            f"Cancelled {ordno} on {unit}; no remaining stops — truck released"
            if released
            else f"Cancelled {ordno} on {unit}; no remaining stops"
        )
        return CancelResponse(
            cancelled_order_id=order_id,
            ordno=ordno,
            truck_id=truck_id,
            unit_number=unit,
            reason=reason,
            assignment=None,
            remaining_order_ids=[],
            remaining_ordnos=[],
        )

    if assignment is None:
        reason = (
            f"Cancelled {ordno} on {unit}; could not rebuild route for "
            f"{len(remaining)} remaining — stop order left as-is where possible"
        )
    else:
        reason = (
            f"Cancelled {ordno} on {unit}; re-optimized "
            f"{len(remaining)} remaining stop(s)"
        )

    return CancelResponse(
        cancelled_order_id=order_id,
        ordno=ordno,
        truck_id=truck_id,
        unit_number=unit,
        reason=reason,
        assignment=assignment,
        remaining_order_ids=[o.id for o in remaining],
        remaining_ordnos=[o.ordno for o in remaining],
    )
