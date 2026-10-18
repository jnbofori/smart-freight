"""Mid-day truck breakdown: report (propose rescue) then approve (transfer load)."""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.enums import DriverStatus, OrderStatus, TruckStatus
from app.models import Driver, Order, Truck
from app.schemas import (
    BreakdownApproveResponse,
    BreakdownReportResponse,
    DispatchReject,
    TruckAssignment,
)
from app.services.dispatch import (
    _capable_sort_key,
    _free_capacity,
    _lost_to_winner_reason,
    _remaining_on_truck,
)
from app.services.optimizer import (
    _TruckLoad,
    _build_assignment,
    _build_load_for_sequence,
    _dest_place,
    _driver_compatible,
    _driver_for_truck,
    _equipment_compatible,
    _optimize_stop_order,
    _truck_delivery_compatible,
)
from app.services.simulate import truck_current_place
from app.services.travel import utc_now_naive_fallback
from app.services.travel_provider import TravelProvider


def _ordered_remaining(truck: Truck, orders: list[Order]) -> list[Order]:
    rem = _remaining_on_truck(truck, orders)
    return sorted(
        rem,
        key=lambda o: (o.stop_seq is None, o.stop_seq if o.stop_seq is not None else 0, o.ordno),
    )


def _delivered_on_truck(truck: Truck, orders: list[Order]) -> list[Order]:
    delivered = [
        o
        for o in orders
        if o.assigned_truck_id == truck.id and o.status == OrderStatus.DELIVERED.value
    ]
    return sorted(
        delivered,
        key=lambda o: (o.stop_seq is None, o.stop_seq if o.stop_seq is not None else 0, o.ordno),
    )


def _place_mid_leg(
    travel: TravelProvider,
    from_place: str,
    to_place: str,
) -> tuple[str, float | None, float | None]:
    """Set breakdown location ~midpoint of from→to (HERE shape or geocode midpoint)."""
    leg = travel.travel(from_place, to_place, live=travel.mode == "live")
    shape = list(leg.shape) if leg.shape else []
    if len(shape) >= 2:
        mid = shape[len(shape) // 2]
        lat, lng = float(mid.lat), float(mid.lng)
        label = f"Breakdown near {to_place} ({lat:.4f},{lng:.4f})"
        return label, lat, lng

    a = travel.geocode(from_place)
    b = travel.geocode(to_place)
    if a and b:
        lat = (a.lat + b.lat) / 2.0
        lng = (a.lng + b.lng) / 2.0
        label = f"Breakdown mid-route to {to_place} ({lat:.4f},{lng:.4f})"
        return label, lat, lng

    return from_place or to_place, None, None


def _combined_capacity_reject(
    transfer: list[Order],
    truck: Truck,
    already_aboard: list[Order],
) -> str | None:
    rem_s, rem_w, rem_f = _free_capacity(truck, already_aboard)
    need_s = sum(float(o.skid_spots or 0) for o in transfer)
    need_w = sum(float(o.weight_lbs or 0) for o in transfer)
    need_f = sum(float(o.linear_feet or 0) for o in transfer)
    for order in transfer:
        if order.height_in is not None and order.height_in > truck.max_interior_height_in:
            return (
                f"{order.ordno}: too tall for truck "
                f"({order.height_in:.0f}\" > {truck.max_interior_height_in}\" interior)"
            )
    if need_w > rem_w:
        return f"over weight remaining ({need_w:.0f} > {rem_w:.0f} lb for load transfer)"
    if need_s > rem_s:
        return f"over skid spots remaining ({need_s:.1f} > {rem_s:.1f} for load transfer)"
    if need_f > rem_f:
        return f"over linear feet remaining ({need_f:.1f} > {rem_f:.1f} for load transfer)"
    return None


def _rescue_compatible(
    transfer: list[Order],
    truck: Truck,
    driver: Driver,
    already_aboard: list[Order],
) -> str | None:
    for order in transfer:
        eq = _equipment_compatible(order, truck)
        if eq:
            return f"{order.ordno}: {eq}"
        td = _truck_delivery_compatible(order, truck)
        if td:
            return f"{order.ordno}: {td}"
        dq = _driver_compatible(order, truck, driver)
        if dq:
            return f"{order.ordno}: driver {driver.code}: {dq}"
    return _combined_capacity_reject(transfer, truck, already_aboard)


def _rebuild_rescue_tour(
    rescue: Truck,
    driver: Driver,
    transfer: list[Order],
    rescue_remaining: list[Order],
    breakdown_place: str,
    day: date,
    travel: TravelProvider,
) -> TruckAssignment | None:
    """Tour from breakdown site; all dest-only (freight already at scene / aboard)."""
    pool = list(transfer) + [o for o in rescue_remaining if o.id not in {t.id for t in transfer}]
    # Empty pickup set → dest-only for every stop
    pickup_ids: set[int] = set()
    from app.enums import MID_SHIFT_CLOCK_MIN

    start_time = float(MID_SHIFT_CLOCK_MIN)
    stub = _TruckLoad(
        truck=rescue,
        driver=driver,
        orders=list(pool),
        current_place=breakdown_place,
        current_time_min=start_time,
    )
    optimized = _optimize_stop_order(
        stub,
        day,
        travel,
        breakdown_place,
        start_place=breakdown_place,
        start_time_min=start_time,
        pickup_order_ids=pickup_ids,
    )
    if optimized.route_stops and len(optimized.route_stops) == len(optimized.orders):
        return _build_assignment(optimized)

    alone = _build_load_for_sequence(
        rescue,
        driver,
        pool,
        day,
        travel,
        breakdown_place,
        start_place=breakdown_place,
        start_time_min=start_time,
        pickup_order_ids=pickup_ids,
        live=travel.mode == "live",
    )
    if alone is None and transfer:
        alone = _build_load_for_sequence(
            rescue,
            driver,
            transfer,
            day,
            travel,
            breakdown_place,
            start_place=breakdown_place,
            start_time_min=start_time,
            pickup_order_ids=pickup_ids,
            live=travel.mode == "live",
        )
    if alone is None:
        return None
    return _build_assignment(alone)


def _rank_rescues(
    *,
    broken: Truck,
    transfer: list[Order],
    breakdown_place: str,
    trucks: list[Truck],
    drivers: list[Driver],
    all_orders: list[Order],
    travel: TravelProvider,
) -> tuple[
    list[tuple[float, Truck, Driver, list[Order]]],
    list[DispatchReject],
]:
    rejects: list[DispatchReject] = []
    capable: list[tuple[float, Truck, Driver, list[Order]]] = []

    for truck in trucks:
        if truck.id == broken.id:
            continue
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

        aboard = _remaining_on_truck(truck, all_orders)
        reason = _rescue_compatible(transfer, truck, driver, aboard)
        if reason:
            rejects.append(
                DispatchReject(truck_id=truck.id, unit_number=truck.unit_number, reason=reason)
            )
            continue

        from_place = truck_current_place(truck, driver)
        travel_min = float(travel.travel(from_place, breakdown_place, live=False).minutes)
        capable.append((travel_min, truck, driver, aboard))

    capable.sort(key=lambda c: _capable_sort_key(c[0], c[1], c[3]))
    return capable, rejects


def report_breakdown(db: Session, truck_id: int) -> BreakdownReportResponse:
    travel = TravelProvider.create()
    day = utc_now_naive_fallback()
    trucks = db.query(Truck).all()
    drivers = db.query(Driver).all()
    all_orders = db.query(Order).all()

    broken = next((t for t in trucks if t.id == truck_id), None)
    if broken is None:
        return BreakdownReportResponse(
            broken_truck_id=truck_id,
            broken_unit_number="",
            breakdown_address="",
            reason="truck not found",
        )

    driver = _driver_for_truck(broken, drivers)
    driver_label = (
        f"{driver.name} ({driver.code})" if driver is not None else "no driver"
    )
    truck_driver_label = f"{broken.unit_number} / {driver_label}"

    transfer = _ordered_remaining(broken, all_orders)
    fulfilled = _delivered_on_truck(broken, all_orders)
    if not transfer:
        return BreakdownReportResponse(
            broken_truck_id=broken.id,
            broken_unit_number=broken.unit_number,
            broken_driver_name=driver.name if driver else None,
            broken_driver_code=driver.code if driver else None,
            breakdown_address=truck_current_place(broken),
            delivered_order_ids=[o.id for o in fulfilled],
            delivered_ordnos=[o.ordno for o in fulfilled],
            reason=(
                f"{truck_driver_label} has no remaining undelivered orders "
                f"(fulfilled: {', '.join(o.ordno for o in fulfilled) or 'none'})"
            ),
        )

    start = truck_current_place(broken, driver)
    next_dest = _dest_place(transfer[0])
    addr, lat, lng = _place_mid_leg(travel, start, next_dest)

    broken.current_address = addr
    broken.current_lat = lat
    broken.current_lng = lng
    broken.status = TruckStatus.OUT_OF_SERVICE.value
    if driver is not None:
        driver.status = DriverStatus.OUT_OF_SERVICE.value
    db.commit()

    fulfilled_list = ", ".join(o.ordno for o in fulfilled) or "none"
    remaining_list = ", ".join(o.ordno for o in transfer)

    capable, rejects = _rank_rescues(
        broken=broken,
        transfer=transfer,
        breakdown_place=addr,
        trucks=trucks,
        drivers=drivers,
        all_orders=all_orders,
        travel=travel,
    )

    if not capable:
        return BreakdownReportResponse(
            broken_truck_id=broken.id,
            broken_unit_number=broken.unit_number,
            broken_driver_name=driver.name if driver else None,
            broken_driver_code=driver.code if driver else None,
            breakdown_address=addr,
            breakdown_lat=lat,
            breakdown_lng=lng,
            delivered_order_ids=[o.id for o in fulfilled],
            delivered_ordnos=[o.ordno for o in fulfilled],
            remaining_order_ids=[o.id for o in transfer],
            remaining_ordnos=[o.ordno for o in transfer],
            reason=(
                f"{truck_driver_label} {addr}. "
                f"Fulfilled: {fulfilled_list}. Remaining: {remaining_list}. "
                f"No capable rescue truck — load stranded pending dispatcher action."
            ),
            rejects=rejects,
        )

    travel_min, winner, win_driver, win_aboard = capable[0]
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
                    winner_remaining=win_aboard,
                ),
            )
        )

    preview = _rebuild_rescue_tour(
        winner, win_driver, transfer, win_aboard, addr, day, travel
    )

    return BreakdownReportResponse(
        broken_truck_id=broken.id,
        broken_unit_number=broken.unit_number,
        broken_driver_name=driver.name if driver else None,
        broken_driver_code=driver.code if driver else None,
        breakdown_address=addr,
        breakdown_lat=lat,
        breakdown_lng=lng,
        delivered_order_ids=[o.id for o in fulfilled],
        delivered_ordnos=[o.ordno for o in fulfilled],
        remaining_order_ids=[o.id for o in transfer],
        remaining_ordnos=[o.ordno for o in transfer],
        recommended_truck_id=winner.id,
        recommended_unit_number=winner.unit_number,
        travel_min_to_breakdown=travel_min,
        reason=(
            f"{truck_driver_label} {addr}. "
            f"Fulfilled: {fulfilled_list}. Remaining: {remaining_list}. "
            f"Recommend rescue {winner.unit_number} / {win_driver.name} ({win_driver.code}) "
            f"({travel_min:.0f} min to breakdown). Awaiting dispatcher approval."
        ),
        rejects=rejects,
        preview_assignment=preview,
    )


def approve_breakdown(
    db: Session,
    truck_id: int,
    rescue_truck_id: int,
    *,
    persist: bool = True,
) -> BreakdownApproveResponse:
    travel = TravelProvider.create()
    day = utc_now_naive_fallback()
    trucks = db.query(Truck).all()
    drivers = db.query(Driver).all()
    all_orders = db.query(Order).all()

    broken = next((t for t in trucks if t.id == truck_id), None)
    if broken is None:
        return BreakdownApproveResponse(
            broken_truck_id=truck_id,
            broken_unit_number="",
            reason="truck not found",
        )
    if broken.status != TruckStatus.OUT_OF_SERVICE.value:
        return BreakdownApproveResponse(
            broken_truck_id=broken.id,
            broken_unit_number=broken.unit_number,
            reason="truck is not out of service — report breakdown first",
        )

    transfer = _ordered_remaining(broken, all_orders)
    if not transfer:
        return BreakdownApproveResponse(
            broken_truck_id=broken.id,
            broken_unit_number=broken.unit_number,
            reason="no remaining undelivered orders to transfer",
        )

    rescue = next((t for t in trucks if t.id == rescue_truck_id), None)
    if rescue is None:
        return BreakdownApproveResponse(
            broken_truck_id=broken.id,
            broken_unit_number=broken.unit_number,
            reason="rescue truck not found",
        )
    if rescue.id == broken.id:
        return BreakdownApproveResponse(
            broken_truck_id=broken.id,
            broken_unit_number=broken.unit_number,
            reason="rescue truck cannot be the broken truck",
        )

    breakdown_place = truck_current_place(broken)
    capable, rejects = _rank_rescues(
        broken=broken,
        transfer=transfer,
        breakdown_place=breakdown_place,
        trucks=trucks,
        drivers=drivers,
        all_orders=all_orders,
        travel=travel,
    )
    winner_row = next((c for c in capable if c[1].id == rescue.id), None)
    if winner_row is None:
        return BreakdownApproveResponse(
            broken_truck_id=broken.id,
            broken_unit_number=broken.unit_number,
            reason="selected rescue truck is not capable of taking the load",
            rejects=rejects,
            transferred_order_ids=[o.id for o in transfer],
            transferred_ordnos=[o.ordno for o in transfer],
        )

    travel_min, winner, win_driver, win_aboard = winner_row
    for mins, truck, _d, rem in capable:
        if truck.id == winner.id:
            continue
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
                    winner_remaining=win_aboard,
                ),
            )
        )

    assignment = _rebuild_rescue_tour(
        winner, win_driver, transfer, win_aboard, breakdown_place, day, travel
    )

    if persist:
        for order in transfer:
            order.assigned_truck_id = winner.id
            order.assigned_driver_id = win_driver.id
            order.status = OrderStatus.ASSIGNED.value
        if assignment and assignment.route and assignment.route.stops:
            by_id = {o.id: o for o in all_orders}
            for stop in assignment.route.stops:
                o = by_id.get(stop.order_id)
                if o is not None:
                    o.stop_seq = stop.seq
        if winner.status != TruckStatus.OUT_OF_SERVICE.value:
            winner.status = TruckStatus.ASSIGNED.value
        if win_driver.status not in {
            DriverStatus.OFF.value,
            DriverStatus.OUT_OF_SERVICE.value,
        }:
            win_driver.status = DriverStatus.ASSIGNED.value
        # Rescue moves to breakdown site after accepting transfer
        winner.current_address = breakdown_place
        winner.current_lat = broken.current_lat
        winner.current_lng = broken.current_lng
        db.commit()

    return BreakdownApproveResponse(
        broken_truck_id=broken.id,
        broken_unit_number=broken.unit_number,
        rescue_truck_id=winner.id,
        rescue_unit_number=winner.unit_number,
        travel_min_to_breakdown=travel_min,
        reason=(
            f"Approved: transferred {len(transfer)} order(s) from {broken.unit_number} "
            f"to {winner.unit_number} / {win_driver.code} "
            f"({travel_min:.0f} min to breakdown)"
        ),
        rejects=rejects,
        assignment=assignment,
        transferred_order_ids=[o.id for o in transfer],
        transferred_ordnos=[o.ordno for o in transfer],
    )
