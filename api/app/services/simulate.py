"""Advance a persisted morning plan partway through the day (demo mid-day)."""

from __future__ import annotations

import random
from collections import defaultdict

from sqlalchemy.orm import Session

from app.enums import OrderStatus, TruckStatus
from app.models import Driver, Order, Truck
from app.schemas import MapPoint, SimulatedTruck, SimulateResponse
from app.services.optimizer import _depot_place, _dest_place, _driver_for_truck
from app.services.travel_provider import TravelProvider


def truck_current_place(truck: Truck, driver: Driver | None = None) -> str:
    addr = (truck.current_address or "").strip()
    if addr:
        return addr
    return _depot_place(truck, driver)


def _append_shape(path: list[MapPoint], shape: list) -> None:
    for pt in shape:
        lat = getattr(pt, "lat", None)
        lng = getattr(pt, "lng", None)
        if lat is None or lng is None:
            continue
        if not path or abs(path[-1].lat - lat) > 1e-5 or abs(path[-1].lng - lng) > 1e-5:
            path.append(MapPoint(lat=float(lat), lng=float(lng)))


def _remaining_road_path(
    travel: TravelProvider,
    start_place: str,
    start_lat: float | None,
    start_lng: float | None,
    remaining: list[Order],
) -> list[MapPoint]:
    """Polyline from current place through remaining destinations (HERE when live)."""
    path: list[MapPoint] = []
    if start_lat is not None and start_lng is not None:
        path.append(MapPoint(lat=start_lat, lng=start_lng))
    else:
        coords = travel.geocode(start_place)
        if coords:
            path.append(MapPoint(lat=coords.lat, lng=coords.lng))

    prev = start_place
    for order in remaining:
        dest = _dest_place(order)
        leg = travel.travel(prev, dest)
        _append_shape(path, leg.shape)
        prev = dest
    return path


def _planned_stop_order(
    orders: list[Order],
    truck: Truck,
    driver: Driver | None,
    travel: TravelProvider,
) -> list[Order]:
    """Morning plan order via stop_seq; legacy fallback nearest-from-depot."""
    if any(o.stop_seq is not None for o in orders):
        return sorted(
            orders,
            key=lambda o: (o.stop_seq is None, o.stop_seq if o.stop_seq is not None else 0, o.ordno),
        )
    depot = _depot_place(truck, driver)
    return sorted(
        orders,
        key=lambda o: (
            float(travel.travel(depot, _dest_place(o)).minutes),
            o.ordno,
        ),
    )


def simulate_midday(db: Session) -> SimulateResponse:
    """Mark a random prefix of each truck's planned stops as delivered; move truck there."""
    travel = TravelProvider.create()
    trucks = db.query(Truck).all()
    drivers = db.query(Driver).all()
    assigned = (
        db.query(Order)
        .filter(Order.status == OrderStatus.ASSIGNED.value)
        .filter(Order.assigned_truck_id.isnot(None))
        .all()
    )
    by_truck: dict[int, list[Order]] = defaultdict(list)
    for order in assigned:
        by_truck[int(order.assigned_truck_id)].append(order)

    moved: list[SimulatedTruck] = []
    total_delivered = 0
    total_remaining = 0

    for truck in trucks:
        orders = by_truck.get(truck.id, [])
        if len(orders) < 2:
            total_remaining += len(orders)
            continue

        driver = _driver_for_truck(truck, drivers)
        ordered = _planned_stop_order(orders, truck, driver, travel)
        n = len(ordered)
        # Random how many, but always a prefix of the planned sequence
        deliver_count = random.randint(1, n - 1)

        to_deliver = ordered[:deliver_count]
        remaining = ordered[deliver_count:]
        last = to_deliver[-1]
        dest = _dest_place(last)
        coords = travel.geocode(dest)

        for order in to_deliver:
            order.status = OrderStatus.DELIVERED.value

        truck.current_address = dest
        truck.current_lat = coords.lat if coords else None
        truck.current_lng = coords.lng if coords else None
        if remaining and truck.status != TruckStatus.OUT_OF_SERVICE.value:
            truck.status = TruckStatus.ASSIGNED.value

        road_path = _remaining_road_path(
            travel,
            dest,
            truck.current_lat,
            truck.current_lng,
            remaining,
        )

        moved.append(
            SimulatedTruck(
                truck_id=truck.id,
                unit_number=truck.unit_number,
                delivered_order_ids=[o.id for o in to_deliver],
                delivered_ordnos=[o.ordno for o in to_deliver],
                remaining_order_ids=[o.id for o in remaining],
                current_address=dest,
                current_lat=truck.current_lat,
                current_lng=truck.current_lng,
                path=road_path,
            )
        )
        total_delivered += len(to_deliver)
        total_remaining += len(remaining)

    db.commit()
    return SimulateResponse(
        trucks_moved=moved,
        summary={
            "trucks_moved": len(moved),
            "orders_delivered": total_delivered,
            "orders_remaining": total_remaining,
        },
    )
