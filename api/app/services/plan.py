"""Rebuild OptimizeResponse from persisted truck/order assignments."""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy.orm import Session

from app.enums import OrderStatus
from app.models import Driver, Order, Truck
from app.schemas import (
    AssignmentRoute,
    CapacityUsage,
    MapPoint,
    OptimizeResponse,
    RouteStop,
    TruckAssignment,
    UnassignedOrder,
)
from app.enums import MID_SHIFT_CLOCK_MIN
from app.services.optimizer import (
    _build_assignment,
    _build_load_for_sequence,
    _depot_place,
    _dest_place,
    _driver_for_truck,
    _enrich_load_map_path,
)
from app.services.simulate import truck_current_place
from app.services.travel import utc_now_naive_fallback
from app.services.travel_provider import TravelProvider


def _ordered_remaining(orders: list[Order]) -> list[Order]:
    return sorted(
        orders,
        key=lambda o: (
            o.stop_seq is None,
            o.stop_seq if o.stop_seq is not None else 0,
            o.ordno,
        ),
    )


def _is_midday(truck: Truck, home: str) -> bool:
    if truck.current_lat is not None and truck.current_lng is not None:
        return True
    addr = (truck.current_address or "").strip()
    return bool(addr) and addr != home


def _append_shape(path: list[MapPoint], shape: list) -> None:
    for pt in shape or []:
        lat = float(getattr(pt, "lat", 0))
        lng = float(getattr(pt, "lng", 0))
        if not path or abs(path[-1].lat - lat) > 1e-5 or abs(path[-1].lng - lng) > 1e-5:
            path.append(MapPoint(lat=lat, lng=lng))


def _fallback_assignment(
    truck: Truck,
    driver: Driver | None,
    orders: list[Order],
    travel: TravelProvider,
    *,
    start_place: str | None,
    pickup_order_ids: set[int] | None,
) -> TruckAssignment:
    """Display-only rebuild when constraint rebuild fails (windows, etc.)."""
    origin = start_place or _depot_place(truck, driver)
    use_live = travel.mode == "live"
    depot_lat = truck.current_lat if start_place else None
    depot_lng = truck.current_lng if start_place else None
    if depot_lat is None or depot_lng is None:
        coords = travel.geocode(origin)
        if coords:
            depot_lat, depot_lng = coords.lat, coords.lng

    path: list[MapPoint] = []
    if depot_lat is not None and depot_lng is not None:
        path.append(MapPoint(lat=depot_lat, lng=depot_lng))

    stops: list[RouteStop] = []
    prev = origin
    eta = float(MID_SHIFT_CLOCK_MIN) if start_place else 0.0
    total_distance = 0.0
    for i, order in enumerate(orders):
        dest = _dest_place(order)
        if pickup_order_ids is not None:
            need_pickup = order.id in pickup_order_ids
        else:
            need_pickup = i == 0

        if need_pickup:
            pickup = (order.origin_address or "").strip() or order.origin_city
            leg1 = travel.travel(prev, pickup, live=use_live)
            leg2 = travel.travel(pickup, dest, live=use_live)
            _append_shape(path, leg1.shape)
            _append_shape(path, leg2.shape)
            travel_min = float(leg1.minutes) + float(leg2.minutes)
            total_distance += float(leg1.distance_m or 0) + float(leg2.distance_m or 0)
        else:
            leg = travel.travel(prev, dest, live=use_live)
            _append_shape(path, leg.shape)
            travel_min = float(leg.minutes)
            total_distance += float(leg.distance_m or 0)

        eta += travel_min
        stop_coords = travel.geocode(dest)
        stops.append(
            RouteStop(
                order_id=order.id,
                ordno=order.ordno,
                seq=i,
                destination_city=order.destination_city,
                destination_address=order.destination_address or "",
                eta_min=eta,
                travel_min_from_prev=travel_min,
                lat=stop_coords.lat if stop_coords else None,
                lng=stop_coords.lng if stop_coords else None,
            )
        )
        prev = dest

    used_w = sum(float(o.weight_lbs or 0) for o in orders)
    used_s = sum(float(o.skid_spots or 0) for o in orders)
    used_f = sum(float(o.linear_feet or 0) for o in orders)
    return TruckAssignment(
        truck_id=truck.id,
        unit_number=truck.unit_number,
        driver_id=driver.id if driver else None,
        driver_name=driver.name if driver else None,
        driver_code=driver.code if driver else None,
        truck_status=truck.status,
        duty_minutes_used=max(
            0.0, eta - (float(MID_SHIFT_CLOCK_MIN) if start_place else 0.0)
        ),
        order_ids=[o.id for o in orders],
        order_ordnos=[o.ordno for o in orders],
        destinations=sorted({_dest_place(o) for o in orders}),
        usage=CapacityUsage(
            weight_lbs=used_w,
            skid_spots=used_s,
            linear_feet=used_f,
            remaining_weight_lbs=float(truck.max_weight_lbs) - used_w,
            remaining_skid_spots=float(truck.max_skid_spots) - used_s,
            remaining_linear_feet=float(truck.max_linear_feet) - used_f,
        ),
        rationales=["Restored from persisted plan"],
        placements=[],
        max_skid_spots=float(truck.max_skid_spots),
        max_linear_feet=float(truck.max_linear_feet),
        max_interior_height_in=int(truck.max_interior_height_in),
        route=AssignmentRoute(
            stops=stops,
            total_distance_m=total_distance,
            total_drive_min=max(
                0.0, eta - (float(MID_SHIFT_CLOCK_MIN) if start_place else 0.0)
            ),
            corridor="unknown",
            path=path,
            depot_lat=depot_lat,
            depot_lng=depot_lng,
            depot_label=origin,
            truck_at_start=bool(start_place),
        ),
    )


def load_persisted_plan(db: Session) -> OptimizeResponse:
    """Reconstruct the current plan from assigned orders in the database."""
    travel = TravelProvider.create()
    day = utc_now_naive_fallback()
    trucks = db.query(Truck).all()
    truck_by_id = {t.id: t for t in trucks}
    drivers = db.query(Driver).all()

    assigned = (
        db.query(Order)
        .filter(Order.status == OrderStatus.ASSIGNED.value)
        .all()
    )
    unassigned_orders = (
        db.query(Order)
        .filter(Order.status == OrderStatus.UNASSIGNED.value)
        .all()
    )

    by_truck: dict[int, list[Order]] = defaultdict(list)
    for order in assigned:
        if order.assigned_truck_id is None:
            continue
        by_truck[order.assigned_truck_id].append(order)

    assignments: list[TruckAssignment] = []
    for truck_id, group in sorted(by_truck.items(), key=lambda item: item[0]):
        truck = truck_by_id.get(truck_id)
        if truck is None:
            continue
        orders = _ordered_remaining(group)
        if not orders:
            continue
        driver = _driver_for_truck(truck, drivers)
        home = _depot_place(truck, driver)
        midday = _is_midday(truck, home)
        start_place = truck_current_place(truck, driver) if midday else None
        start_time = float(MID_SHIFT_CLOCK_MIN) if midday else None
        # Remaining freight is already aboard after simulate/dispatch/breakdown.
        pickup_ids: set[int] | None = set() if midday else None
        depot = home

        load = None
        if driver is not None:
            load = _build_load_for_sequence(
                truck,
                driver,
                orders,
                day,
                travel,
                depot,
                start_place=start_place,
                start_time_min=start_time,
                pickup_order_ids=pickup_ids,
                live=False,
            )
            if load is not None and travel.mode == "live":
                _enrich_load_map_path(
                    load,
                    travel,
                    start_place=start_place,
                    pickup_order_ids=pickup_ids,
                )
            if load is not None and midday and truck.current_lat is not None:
                load.depot_lat = truck.current_lat
                load.depot_lng = truck.current_lng
                load.depot_label = start_place or home
                load.truck_at_start = True
                if load.path_points and truck.current_lng is not None:
                    load.path_points[0] = MapPoint(
                        lat=float(truck.current_lat),
                        lng=float(truck.current_lng),
                    )

        if load is not None:
            assignments.append(_build_assignment(load))
        else:
            assignments.append(
                _fallback_assignment(
                    truck,
                    driver,
                    orders,
                    travel,
                    start_place=start_place,
                    pickup_order_ids=pickup_ids,
                )
            )

    unassigned = [
        UnassignedOrder(order_id=o.id, ordno=o.ordno, reason="unassigned")
        for o in sorted(unassigned_orders, key=lambda o: o.ordno)
    ]
    assigned_count = sum(len(a.order_ids) for a in assignments)
    return OptimizeResponse(
        assignments=assignments,
        unassigned=unassigned,
        summary={
            "trucks_used": len(assignments),
            "drivers_used": len({a.driver_id for a in assignments if a.driver_id}),
            "orders_assigned": assigned_count,
            "orders_unassigned": len(unassigned),
            "orders_considered": assigned_count + len(unassigned),
        },
        planning_date=day,
        routing_mode=travel.mode,
        weather_summary=travel.weather_summary(),
    )
