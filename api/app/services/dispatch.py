"""Closest-capable mid-day pickup dispatch onto remaining truck tours."""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.enums import DriverStatus, OrderStatus, TruckStatus
from app.models import Driver, Order, Truck
from app.schemas import (
    DispatchReject,
    DispatchResponse,
    TruckAssignment,
)
from app.services.optimizer import (
    _TruckLoad,
    _build_assignment,
    _build_load_for_sequence,
    _driver_compatible,
    _driver_for_truck,
    _equipment_compatible,
    _optimize_stop_order,
    _origin_place,
    _truck_delivery_compatible,
)
from app.enums import MID_SHIFT_CLOCK_MIN
from app.services.simulate import truck_current_place
from app.services.travel import utc_now_naive_fallback
from app.services.travel_provider import TravelProvider


def _remaining_on_truck(truck: Truck, orders: list[Order]) -> list[Order]:
    return [
        o
        for o in orders
        if o.assigned_truck_id == truck.id and o.status == OrderStatus.ASSIGNED.value
    ]


def _free_capacity(truck: Truck, remaining: list[Order]) -> tuple[float, float, float]:
    """Remaining (skids, weight_lbs, linear_feet) after freight still aboard."""
    used_w = sum(float(o.weight_lbs or 0) for o in remaining)
    used_s = sum(float(o.skid_spots or 0) for o in remaining)
    used_f = sum(float(o.linear_feet or 0) for o in remaining)
    return (
        float(truck.max_skid_spots) - used_s,
        float(truck.max_weight_lbs) - used_w,
        float(truck.max_linear_feet) - used_f,
    )


def _capacity_reject(order: Order, truck: Truck, remaining: list[Order]) -> str | None:
    """Hard capacity vs freight still aboard (assigned, not delivered)."""
    rem_s, rem_w, rem_f = _free_capacity(truck, remaining)
    if order.height_in is not None and order.height_in > truck.max_interior_height_in:
        return (
            f"too tall for truck "
            f"({order.height_in:.0f}\" > {truck.max_interior_height_in}\" interior)"
        )
    if order.weight_lbs > rem_w:
        return f"over weight remaining ({order.weight_lbs:.0f} > {rem_w:.0f} lb)"
    if float(order.skid_spots or 0) > rem_s:
        return (
            f"over skid spots remaining "
            f"({float(order.skid_spots or 0):.1f} > {rem_s:.1f})"
        )
    if order.linear_feet > rem_f:
        return (
            f"over linear feet remaining "
            f"({order.linear_feet:.1f} > {rem_f:.1f})"
        )
    return None


def _capable_sort_key(
    travel_min: float,
    truck: Truck,
    remaining: list[Order],
) -> tuple:
    """Closest first; on tie prefer more free capacity, then unit number."""
    free_s, free_w, free_f = _free_capacity(truck, remaining)
    return (travel_min, -free_s, -free_w, -free_f, truck.unit_number)


def _lost_to_winner_reason(
    *,
    mins: float,
    truck: Truck,
    remaining: list[Order],
    winner_mins: float,
    winner: Truck,
    winner_remaining: list[Order],
) -> str:
    if mins > winner_mins + 0.05:
        return f"farther to pickup ({mins:.0f} min vs {winner_mins:.0f} min)"

    free_s, free_w, free_f = _free_capacity(truck, remaining)
    win_s, win_w, win_f = _free_capacity(winner, winner_remaining)
    if (free_s, free_w, free_f) < (win_s, win_w, win_f):
        return (
            f"same travel time ({mins:.0f} min); less free capacity "
            f"(skids {free_s:.0f}/{win_s:.0f}, lb {free_w:.0f}/{win_w:.0f})"
        )
    return (
        f"same travel time ({mins:.0f} min) and capacity; "
        f"lost tie-break to {winner.unit_number}"
    )


def _rebuild_assignment(
    truck: Truck,
    driver: Driver,
    new_order: Order,
    remaining: list[Order],
    day: date,
    travel: TravelProvider,
) -> TruckAssignment | None:
    """Rebuild remaining tour from truck current place with window/constraint 2-opt.

    Only the new order diverts via its origin (pickup); freight already aboard
    goes current → destination. Hard delivery windows, liftgate/heated/equipment,
    driver hours, and capacity reject infeasible sequences.
    """
    start = truck_current_place(truck, driver)
    start_time = float(MID_SHIFT_CLOCK_MIN)  # mid-shift demo clock (noon)
    pickup_ids = {new_order.id}
    pool = [new_order, *remaining]

    stub = _TruckLoad(
        truck=truck,
        driver=driver,
        orders=list(pool),
        current_place=start,
        current_time_min=start_time,
    )
    optimized = _optimize_stop_order(
        stub,
        day,
        travel,
        start,
        start_place=start,
        start_time_min=start_time,
        pickup_order_ids=pickup_ids,
    )
    if optimized.route_stops and len(optimized.route_stops) == len(optimized.orders):
        return _build_assignment(optimized)

    # Full pool infeasible — assign new pickup alone if possible
    alone = _build_load_for_sequence(
        truck,
        driver,
        [new_order],
        day,
        travel,
        start,
        start_place=start,
        start_time_min=start_time,
        pickup_order_ids=pickup_ids,
        live=travel.mode == "live",
    )
    if alone is None:
        return None
    return _build_assignment(alone)


def dispatch_order(
    db: Session,
    order_id: int,
    *,
    persist: bool = True,
) -> DispatchResponse:
    order = db.query(Order).filter(Order.id == order_id).first()
    if order is None:
        return DispatchResponse(
            order_id=order_id,
            ordno="",
            reason="order not found",
        )
    if order.status not in {OrderStatus.UNASSIGNED.value}:
        return DispatchResponse(
            order_id=order.id,
            ordno=order.ordno,
            reason=f"order status is {order.status}; need unassigned",
        )

    travel = TravelProvider.create()
    day = utc_now_naive_fallback()
    trucks = db.query(Truck).all()
    drivers = db.query(Driver).all()
    all_orders = db.query(Order).all()
    return _dispatch_order_body(
        db,
        order,
        travel=travel,
        day=day,
        trucks=trucks,
        drivers=drivers,
        all_orders=all_orders,
        persist=persist,
    )


def _dispatch_order_body(
    db: Session,
    order: Order,
    *,
    travel: TravelProvider,
    day,
    trucks: list[Truck],
    drivers: list[Driver],
    all_orders: list[Order],
    persist: bool,
) -> DispatchResponse:
    pickup = _origin_place(order)

    rejects: list[DispatchReject] = []
    capable: list[tuple[float, Truck, Driver, list[Order]]] = []

    for truck in trucks:
        if truck.status == TruckStatus.OUT_OF_SERVICE.value:
            rejects.append(
                DispatchReject(
                    truck_id=truck.id,
                    unit_number=truck.unit_number,
                    reason="out of service",
                )
            )
            continue

        driver = _driver_for_truck(truck, drivers)
        if driver is None:
            rejects.append(
                DispatchReject(
                    truck_id=truck.id,
                    unit_number=truck.unit_number,
                    reason="no sticky driver",
                )
            )
            continue
        if driver.status in {
            DriverStatus.OFF.value,
            DriverStatus.OUT_OF_SERVICE.value,
        }:
            rejects.append(
                DispatchReject(
                    truck_id=truck.id,
                    unit_number=truck.unit_number,
                    reason=f"driver {driver.code} is {driver.status}",
                )
            )
            continue

        eq = _equipment_compatible(order, truck)
        if eq:
            rejects.append(
                DispatchReject(truck_id=truck.id, unit_number=truck.unit_number, reason=eq)
            )
            continue
        td = _truck_delivery_compatible(order, truck)
        if td:
            rejects.append(
                DispatchReject(truck_id=truck.id, unit_number=truck.unit_number, reason=td)
            )
            continue
        dq = _driver_compatible(order, truck, driver)
        if dq:
            rejects.append(
                DispatchReject(
                    truck_id=truck.id,
                    unit_number=truck.unit_number,
                    reason=f"driver {driver.code}: {dq}",
                )
            )
            continue

        remaining = _remaining_on_truck(truck, all_orders)
        cap = _capacity_reject(order, truck, remaining)
        if cap:
            rejects.append(
                DispatchReject(truck_id=truck.id, unit_number=truck.unit_number, reason=cap)
            )
            continue

        from_place = truck_current_place(truck, driver)
        travel_min = float(travel.travel(from_place, pickup, live=False).minutes)
        capable.append((travel_min, truck, driver, remaining))

    if not capable:
        return DispatchResponse(
            order_id=order.id,
            ordno=order.ordno,
            reason="no capable truck",
            rejects=rejects,
        )

    capable.sort(key=lambda c: _capable_sort_key(c[0], c[1], c[3]))
    travel_min, winner, driver, remaining = capable[0]

    for mins, truck, _d, rem in capable[1:]:
        rejects.append(
            DispatchReject(
                truck_id=truck.id,
                unit_number=truck.unit_number,
                reason=_lost_to_winner_reason(
                    mins=mins,
                    truck=truck,
                    remaining=rem,
                    winner_mins=travel_min,
                    winner=winner,
                    winner_remaining=remaining,
                ),
            )
        )

    assignment = _rebuild_assignment(winner, driver, order, remaining, day, travel)

    if persist:
        order.assigned_truck_id = winner.id
        order.assigned_driver_id = driver.id
        order.status = OrderStatus.ASSIGNED.value
        if assignment and assignment.route and assignment.route.stops:
            by_id = {o.id: o for o in all_orders}
            by_id[order.id] = order
            for stop in assignment.route.stops:
                o = by_id.get(stop.order_id)
                if o is not None:
                    o.stop_seq = stop.seq
        else:
            order.stop_seq = 0
        if winner.status != TruckStatus.OUT_OF_SERVICE.value:
            winner.status = TruckStatus.ASSIGNED.value
        if driver.status not in {
            DriverStatus.OFF.value,
            DriverStatus.OUT_OF_SERVICE.value,
        }:
            driver.status = DriverStatus.ASSIGNED.value
        db.commit()
        db.refresh(order)

    return DispatchResponse(
        order_id=order.id,
        ordno=order.ordno,
        chosen_truck_id=winner.id,
        chosen_unit_number=winner.unit_number,
        travel_min_to_pickup=travel_min,
        reason=(
            f"Closest capable: {winner.unit_number} / {driver.code} "
            f"({travel_min:.0f} min to pickup from {truck_current_place(winner, driver)})"
        ),
        rejects=rejects,
        assignment=assignment,
    )
