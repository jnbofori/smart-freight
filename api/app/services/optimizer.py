from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from app.enums import (
    MAX_STACK_LAYERS,
    DriverStatus,
    EquipmentRequired,
    LicenceClass,
    OrderStatus,
    TrailerSizeClass,
    TruckStatus,
    VehicleClass,
)
from app.models import Driver, Order, Truck
from app.schemas import (
    AssignmentRoute,
    CapacityUsage,
    LoadPlacement,
    MapPoint,
    OptimizeResponse,
    RouteStop,
    TruckAssignment,
    UnassignedOrder,
)
from app.services.geocode import corridor_affinity
from app.services.travel import (
    effective_window_end_min,
    effective_window_start_min,
    service_minutes,
    utc_now_naive_fallback,
)
from app.services.travel_provider import TravelProvider


def _driver_for_truck(truck: Truck, drivers: list[Driver]) -> Driver | None:
    for d in drivers:
        if d.truck_id == truck.id:
            return d
    return None


def _dest_place(order: Order) -> str:
    return (order.destination_address or "").strip() or order.destination_city


def _origin_place(order: Order) -> str:
    return (order.origin_address or "").strip() or order.origin_city


def _depot_place(truck: Truck, driver: Driver | None = None) -> str:
    if driver and driver.home_terminal_city:
        return driver.home_terminal_city
    return truck.home_terminal_city or "Toronto"


@dataclass
class _StackColumn:
    spots: float
    used_height_in: float
    layers: int


@dataclass
class _FloorState:
    floor_used: float = 0.0
    columns: list[_StackColumn] = field(default_factory=list)

    def remaining_floor(self, max_spots: float) -> float:
        return max_spots - self.floor_used


@dataclass
class _Placement:
    stacked_on_existing: bool
    column_index: int | None
    new_floor_spots: float
    note: str


@dataclass
class _TimePlan:
    arrive_min: float
    depart_min: float
    travel_added: float
    duty_after: float
    drive_after: float
    distance_m: float
    weather_note: str
    note: str
    shape: list = field(default_factory=list)


@dataclass
class _TruckLoad:
    truck: Truck
    driver: Driver | None = None
    orders: list[Order] = field(default_factory=list)  # delivery stop order
    used_weight: float = 0.0
    used_feet: float = 0.0
    floor: _FloorState = field(default_factory=_FloorState)
    rationales: list[str] = field(default_factory=list)
    placements: list[LoadPlacement] = field(default_factory=list)
    column_viz_ids: list[int] = field(default_factory=list)
    next_viz_col: int = 0
    current_place: str = ""
    current_time_min: float = 0.0
    duty_minutes: float = 0.0
    drive_minutes: float = 0.0
    distance_m: float = 0.0
    corridor: str = "unknown"
    route_stops: list[RouteStop] = field(default_factory=list)
    path_points: list[MapPoint] = field(default_factory=list)
    depot_lat: float | None = None
    depot_lng: float | None = None
    depot_label: str = ""
    truck_at_start: bool = False

    @property
    def remaining_weight(self) -> float:
        return self.truck.max_weight_lbs - self.used_weight

    @property
    def remaining_skids(self) -> float:
        return self.floor.remaining_floor(self.truck.max_skid_spots)

    @property
    def remaining_feet(self) -> float:
        return self.truck.max_linear_feet - self.used_feet

    def destinations(self) -> set[str]:
        return {_dest_place(o) for o in self.orders}


def _can_stack(order: Order) -> bool:
    return bool(order.stackable and order.height_in is not None and order.height_in > 0)


def _equipment_compatible(order: Order, truck: Truck) -> str | None:
    req = order.equipment_required
    if req in (EquipmentRequired.ANY.value, EquipmentRequired.ANY):
        return None

    has_53 = truck.has_trailer and truck.trailer_size_class == TrailerSizeClass.FT53.value
    is_tractor = truck.vehicle_class == VehicleClass.TRACTOR.value
    is_truck = truck.vehicle_class == VehicleClass.TRUCK.value
    is_van = truck.vehicle_class == VehicleClass.VAN.value

    if req == EquipmentRequired.TRAILER_53.value:
        return None if has_53 else "requires 53ft trailer"
    if req == EquipmentRequired.TRACTOR.value:
        return None if is_tractor else "requires tractor"
    if req == EquipmentRequired.VAN.value:
        return None if is_van else "requires van"
    if req == EquipmentRequired.TRUCK.value:
        if is_truck or has_53:
            return None
        return "requires truck or 53ft trailer equipment"
    return None


def _truck_delivery_compatible(order: Order, truck: Truck) -> str | None:
    needs_liftgate = order.requires_liftgate or order.residential or order.inside_delivery
    if needs_liftgate and not truck.has_liftgate:
        return "requires liftgate equipment"
    if order.heated and not truck.heated:
        return "requires heated equipment"
    return None


def _driver_compatible(order: Order, truck: Truck, driver: Driver) -> str | None:
    needs_az = (
        truck.vehicle_class == VehicleClass.TRACTOR.value
        or order.equipment_required == EquipmentRequired.TRAILER_53.value
    )
    if needs_az and driver.licence_class not in {
        LicenceClass.AZ.value,
        LicenceClass.DZ.value,
    }:
        # AZ preferred for tractor+53; DZ ok for many straight trucks — require AZ for tractor
        if truck.vehicle_class == VehicleClass.TRACTOR.value and driver.licence_class != LicenceClass.AZ.value:
            return "requires AZ licence for tractor"
    if order.dangerous_goods and not driver.can_dangerous_goods:
        return "no qualified driver (dangerous goods)"
    if order.heated and not driver.can_heated:
        return "no qualified driver (heated)"
    needs_liftgate = order.requires_liftgate or order.residential or order.inside_delivery
    if needs_liftgate and not driver.can_liftgate_runs:
        return "no qualified driver (liftgate)"
    return None


def _find_placement(order: Order, load: _TruckLoad) -> tuple[_Placement | None, str | None]:
    truck = load.truck
    max_h = truck.max_interior_height_in

    if order.height_in is not None and order.height_in > max_h:
        return None, (
            f"too tall for truck ({order.height_in:.0f}\" > {max_h}\" interior)"
        )
    if order.weight_lbs > load.remaining_weight:
        return None, (
            f"over weight remaining "
            f"({order.weight_lbs:.0f} > {load.remaining_weight:.0f} lb)"
        )
    if order.linear_feet > load.remaining_feet:
        return None, (
            f"over linear feet remaining "
            f"({order.linear_feet:.1f} > {load.remaining_feet:.1f})"
        )

    spots = float(order.skid_spots or 0)
    if _can_stack(order):
        height = float(order.height_in or 0)
        for idx, col in enumerate(load.floor.columns):
            if col.spots != spots:
                continue
            if col.layers >= MAX_STACK_LAYERS:
                continue
            if col.used_height_in + height > max_h:
                continue
            return (
                _Placement(
                    stacked_on_existing=True,
                    column_index=idx,
                    new_floor_spots=0.0,
                    note=(
                        f"stacked on {spots:g}-spot column "
                        f"({col.used_height_in:.0f}\"+{height:.0f}\" under {max_h}\")"
                    ),
                ),
                None,
            )
        if spots > load.remaining_skids:
            return None, (
                f"no stackable floor room "
                f"(need {spots:g} spots, {load.remaining_skids:.1f} free)"
            )
        return (
            _Placement(
                stacked_on_existing=False,
                column_index=None,
                new_floor_spots=spots,
                note=f"new stackable column {spots:g} spots @ {height:.0f}\"",
            ),
            None,
        )

    if spots > load.remaining_skids:
        return None, (
            f"over skid spots remaining ({spots:.1f} > {load.remaining_skids:.1f})"
        )
    return (
        _Placement(
            stacked_on_existing=False,
            column_index=None,
            new_floor_spots=spots,
            note=f"floor {spots:g} spots",
        ),
        None,
    )


def _apply_placement(
    load: _TruckLoad,
    order: Order,
    placement: _Placement,
    *,
    stop_seq: int,
) -> LoadPlacement:
    if placement.stacked_on_existing and placement.column_index is not None:
        col = load.floor.columns[placement.column_index]
        layer = col.layers
        col.used_height_in += float(order.height_in or 0)
        col.layers += 1
        viz_col = load.column_viz_ids[placement.column_index]
        rec = LoadPlacement(
            order_id=order.id,
            ordno=order.ordno,
            column_index=viz_col,
            layer=layer,
            floor_spots=0.0,
            skid_spots=float(order.skid_spots or 0),
            linear_feet=float(order.linear_feet or 0),
            height_in=order.height_in,
            stackable=bool(order.stackable),
            stacked=True,
            stop_seq=stop_seq,
            load_seq=0,  # filled in finalize
        )
        load.placements.append(rec)
        return rec

    load.floor.floor_used += placement.new_floor_spots
    viz_col = load.next_viz_col
    load.next_viz_col += 1
    if _can_stack(order) and placement.new_floor_spots > 0:
        load.floor.columns.append(
            _StackColumn(
                spots=placement.new_floor_spots,
                used_height_in=float(order.height_in or 0),
                layers=1,
            )
        )
        load.column_viz_ids.append(viz_col)

    rec = LoadPlacement(
        order_id=order.id,
        ordno=order.ordno,
        column_index=viz_col,
        layer=0,
        floor_spots=placement.new_floor_spots,
        skid_spots=float(order.skid_spots or 0),
        linear_feet=float(order.linear_feet or 0),
        height_in=order.height_in,
        stackable=bool(order.stackable),
        stacked=False,
        stop_seq=stop_seq,
        load_seq=0,
    )
    load.placements.append(rec)
    return rec


def _finalize_lifo_placements(load: _TruckLoad) -> None:
    """load_seq: 0 = nose (loaded first), highest = door (first stop / LIFO)."""
    n = len(load.orders)
    if n == 0:
        return
    stop_to_load = {i: n - 1 - i for i in range(n)}
    for p in load.placements:
        p.load_seq = stop_to_load.get(p.stop_seq, 0)


def _simulate_time(
    order: Order,
    load: _TruckLoad,
    driver: Driver,
    planning_date: date,
    travel: TravelProvider,
    *,
    need_pickup: bool | None = None,
    live: bool = False,
) -> tuple[_TimePlan | None, str | None]:
    """
    Time a stop onto the load.
    need_pickup: True = divert via order origin; False = dest only;
    None = morning default (pickup only when the load is still empty).
    live: False = static table (scoring); True = HERE + weather (commit / map).
    """
    depot = _depot_place(load.truck, driver)
    start_place = load.current_place or depot
    if not load.orders:
        clock = float(
            max(
                driver.shift_start_min,
                effective_window_start_min(
                    planning_date=planning_date,
                    delivery_window_start=None,
                    driver_shift_start_min=driver.shift_start_min,
                ),
            )
        )
        # Mid-day rebuilds pass start_time_min on the load; prefer that clock.
        if load.current_time_min > 0:
            clock = float(load.current_time_min)
        duty = 0.0
        drive = 0.0
        from_place = start_place or _origin_place(order)
    else:
        clock = load.current_time_min
        duty = load.duty_minutes
        drive = load.drive_minutes
        from_place = load.current_place

    weather_note = ""
    distance_m = 0.0
    shape: list = []
    dest = _dest_place(order)
    origin = _origin_place(order)
    do_pickup = (not load.orders) if need_pickup is None else bool(need_pickup)
    if do_pickup:
        leg1 = travel.travel(from_place, origin, live=live) if from_place else None
        leg2 = travel.travel(origin, dest, live=live)
        t1 = float(leg1.minutes) if leg1 else 0.0
        t2 = float(leg2.minutes)
        travel_min = t1 + t2
        distance_m = (leg1.distance_m if leg1 else 0.0) + leg2.distance_m
        weather_note = ", ".join(
            x for x in [(leg1.weather_note if leg1 else ""), leg2.weather_note] if x
        )
        if leg1 and leg1.shape:
            shape.extend(leg1.shape)
        if leg2.shape:
            shape.extend(leg2.shape[1:] if shape and leg2.shape else leg2.shape)
    else:
        leg = travel.travel(from_place, dest, live=live)
        travel_min = float(leg.minutes)
        distance_m = leg.distance_m
        weather_note = leg.weather_note
        shape = list(leg.shape)

    svc = float(service_minutes())
    arrive = clock + travel_min
    window_open = effective_window_start_min(
        planning_date=planning_date,
        delivery_window_start=order.delivery_window_start,
        driver_shift_start_min=driver.shift_start_min,
    )
    if arrive < window_open:
        arrive = float(window_open)

    due_end, hard = effective_window_end_min(
        planning_date=planning_date,
        service=order.service,
        appointment=order.appointment,
        delivery_window_start=order.delivery_window_start,
        delivery_window_end=order.delivery_window_end,
        driver_shift_end_min=driver.shift_end_min,
    )
    depart = arrive + svc

    soft_miss_note = ""
    if due_end is not None and arrive > due_end:
        msg = (
            f"outside delivery window "
            f"(arrive {arrive:.0f} min > due {due_end} min)"
        )
        if hard:
            return None, msg
        soft_miss_note = f", soft window miss (due≤{due_end})"

    if depart > driver.shift_end_min:
        return None, (
            f"driver hours exceeded "
            f"(depart {depart:.0f} after shift end {driver.shift_end_min})"
        )

    duty_after = duty + travel_min + svc + max(0.0, arrive - (clock + travel_min))
    drive_after = drive + travel_min
    max_duty = driver.max_duty_hours * 60
    max_drive = driver.max_drive_hours * 60
    if duty_after > max_duty:
        return None, (
            f"driver hours exceeded "
            f"(duty {duty_after:.0f} min > max {max_duty:.0f})"
        )
    if drive_after > max_drive:
        return None, (
            f"driver hours exceeded "
            f"(drive {drive_after:.0f} min > max {max_drive:.0f})"
        )

    note = (
        f"ETA {arrive:.0f}–{depart:.0f} min"
        + (f", due≤{due_end}" if due_end is not None and not soft_miss_note else "")
        + soft_miss_note
        + f", duty {duty_after:.0f} min"
    )
    return (
        _TimePlan(
            arrive_min=arrive,
            depart_min=depart,
            travel_added=travel_min,
            duty_after=duty_after,
            drive_after=drive_after,
            distance_m=distance_m,
            weather_note=weather_note,
            note=note,
            shape=shape,
        ),
        None,
    )


def _score(
    order: Order,
    load: _TruckLoad,
    driver: Driver,
    placement: _Placement,
    time_plan: _TimePlan,
    planning_date: date,
    depot: str,
    travel: TravelProvider,
) -> float:
    """Higher is better. Heavily prefers lower insertion travel."""
    truck = load.truck
    score = 0.0

    # Travel-aware insertion cost (dominant term)
    score -= time_plan.travel_added * 2.5
    score -= time_plan.distance_m / 1000.0

    dest = _dest_place(order)
    if dest in load.destinations():
        score += 50.0

    order_corr = travel.corridor(dest, depot)
    if load.orders:
        score += 35.0 * corridor_affinity(load.corridor, order_corr)
    else:
        score += 5.0

    if truck.home_terminal_city.lower() in dest.lower():
        score += 15.0
    if driver.home_terminal_city.lower() in dest.lower():
        score += 10.0

    rem_w = load.remaining_weight - order.weight_lbs
    rem_s = load.remaining_skids - placement.new_floor_spots
    if truck.max_weight_lbs:
        score += 10.0 * (1.0 - rem_w / truck.max_weight_lbs)
    if truck.max_skid_spots:
        score += 8.0 * (1.0 - rem_s / truck.max_skid_spots)
    if placement.stacked_on_existing:
        score += 20.0

    due_end, hard = effective_window_end_min(
        planning_date=planning_date,
        service=order.service,
        appointment=order.appointment,
        delivery_window_start=order.delivery_window_start,
        delivery_window_end=order.delivery_window_end,
        driver_shift_end_min=driver.shift_end_min,
    )
    if due_end is not None:
        slack = due_end - time_plan.arrive_min
        score += max(0.0, min(30.0, slack / 5.0))
        if order.appointment:
            score += 15.0
        if hard and slack < 0:
            score -= 100.0

    needs_liftgate = order.requires_liftgate or order.residential or order.inside_delivery
    if needs_liftgate and truck.has_liftgate and driver.can_liftgate_runs:
        score += 5.0

    return score


def _candidate_driver(
    load: _TruckLoad,
    drivers: list[Driver],
    locked_driver_ids: set[int],
) -> Driver | None:
    if load.driver is not None:
        return load.driver
    driver = _driver_for_truck(load.truck, drivers)
    if driver is None:
        return None
    if driver.status not in {
        DriverStatus.AVAILABLE.value,
        DriverStatus.ASSIGNED.value,
    }:
        return None
    if driver.id in locked_driver_ids:
        return None
    return driver


def _commit_order(
    load: _TruckLoad,
    order: Order,
    driver: Driver,
    placement: _Placement,
    time_plan: _TimePlan,
    locked_driver_ids: set[int],
    travel: TravelProvider,
) -> None:
    if load.driver is None:
        load.driver = driver
        locked_driver_ids.add(driver.id)

    stop_seq = len(load.orders)
    load.orders.append(order)
    load.used_weight += order.weight_lbs
    load.used_feet += order.linear_feet
    _apply_placement(load, order, placement, stop_seq=stop_seq)
    dest = _dest_place(order)
    load.current_place = dest
    load.current_time_min = time_plan.depart_min
    load.duty_minutes = time_plan.duty_after
    load.drive_minutes = time_plan.drive_after
    load.distance_m += time_plan.distance_m

    depot = _depot_place(load.truck, driver)
    if load.corridor == "unknown":
        load.corridor = travel.corridor(dest, depot)

    if load.depot_lat is None:
        depot_coords = travel.geocode(depot)
        if depot_coords:
            load.depot_lat = depot_coords.lat
            load.depot_lng = depot_coords.lng
            load.depot_label = depot
            load.path_points.append(
                MapPoint(lat=depot_coords.lat, lng=depot_coords.lng)
            )

    for pt in time_plan.shape:
        if not load.path_points or (
            abs(load.path_points[-1].lat - pt.lat) > 1e-5
            or abs(load.path_points[-1].lng - pt.lng) > 1e-5
        ):
            load.path_points.append(MapPoint(lat=pt.lat, lng=pt.lng))

    coords = travel.geocode(dest)
    stop_lat = coords.lat if coords else None
    stop_lng = coords.lng if coords else None
    # Fall back to last road-shape point so stop markers always show when path exists
    if (stop_lat is None or stop_lng is None) and time_plan.shape:
        last_pt = time_plan.shape[-1]
        if getattr(last_pt, "lat", None) is not None and getattr(last_pt, "lng", None) is not None:
            stop_lat = float(last_pt.lat)
            stop_lng = float(last_pt.lng)
    load.route_stops.append(
        RouteStop(
            order_id=order.id,
            ordno=order.ordno,
            seq=stop_seq,
            destination_city=order.destination_city,
            destination_address=dest,
            eta_min=time_plan.arrive_min,
            travel_min_from_prev=time_plan.travel_added,
            lat=stop_lat,
            lng=stop_lng,
            weather_note=time_plan.weather_note,
        )
    )
    load.rationales.append(
        f"Assigned {order.ordno} → {load.truck.unit_number} / "
        f"{driver.code} {driver.name} "
        f"(dest={dest}, corridor={load.corridor}, "
        f"{placement.note}, {time_plan.note})"
    )


def _try_assign_order(
    order: Order,
    loads: list[_TruckLoad],
    pool: list[Driver],
    locked_driver_ids: set[int],
    day: date,
    travel: TravelProvider,
    depot: str,
) -> bool:
    # Score with static travel (no HERE / weather). Commit with live when configured.
    candidates: list[tuple[float, _TruckLoad, Driver, _Placement]] = []
    for load in loads:
        if _equipment_compatible(order, load.truck) is not None:
            continue
        if _truck_delivery_compatible(order, load.truck) is not None:
            continue
        placement, cap_reason = _find_placement(order, load)
        if placement is None or cap_reason is not None:
            continue
        driver = _candidate_driver(load, pool, locked_driver_ids)
        if driver is None:
            continue
        if _driver_compatible(order, load.truck, driver) is not None:
            continue
        time_plan, time_reason = _simulate_time(
            order, load, driver, day, travel, live=False
        )
        if time_plan is None or time_reason is not None:
            continue
        score = _score(order, load, driver, placement, time_plan, day, depot, travel)
        candidates.append((score, load, driver, placement))

    if not candidates:
        return False

    candidates.sort(key=lambda c: (-c[0], c[1].truck.unit_number, c[2].code))
    # Commit with static travel; a later pass refreshes ETAs/polylines via HERE.
    for _s, best, driver, _pl in candidates:
        placement, cap = _find_placement(order, best)
        if placement is None or cap is not None:
            continue
        time_plan, time_reason = _simulate_time(
            order, best, driver, day, travel, live=False
        )
        if time_plan is None or time_reason is not None:
            continue
        _commit_order(
            best, order, driver, placement, time_plan, locked_driver_ids, travel
        )
        return True
    return False


def _best_unassigned_reason(
    order: Order,
    loads: list[_TruckLoad],
    drivers: list[Driver],
    locked_driver_ids: set[int],
    planning_date: date,
    travel: TravelProvider,
) -> str:
    reasons: list[str] = []
    for load in loads:
        eq = _equipment_compatible(order, load.truck)
        if eq:
            reasons.append(f"{load.truck.unit_number}: {eq}")
            continue
        td = _truck_delivery_compatible(order, load.truck)
        if td:
            reasons.append(f"{load.truck.unit_number}: {td}")
            continue
        _p, cap = _find_placement(order, load)
        if cap:
            reasons.append(f"{load.truck.unit_number}: {cap}")
            continue
        driver = _candidate_driver(load, drivers, locked_driver_ids)
        if driver is None:
            reasons.append(f"{load.truck.unit_number}: no driver assigned to truck")
            continue
        dq = _driver_compatible(order, load.truck, driver)
        if dq:
            reasons.append(f"{load.truck.unit_number}: {driver.code}: {dq}")
            continue
        _t, tr = _simulate_time(
            order, load, driver, planning_date, travel, live=False
        )
        if tr:
            reasons.append(f"{load.truck.unit_number}: {driver.code}: {tr}")
        else:
            reasons.append(f"{load.truck.unit_number}: feasible but not selected")
    if not reasons:
        return "no feasible truck/driver"
    return "; ".join(reasons[:4]) + ("…" if len(reasons) > 4 else "")


def _build_load_for_sequence(
    truck: Truck,
    driver: Driver,
    orders: list[Order],
    day: date,
    travel: TravelProvider,
    depot: str,
    *,
    start_place: str | None = None,
    start_time_min: float | None = None,
    pickup_order_ids: set[int] | None = None,
    live: bool = False,
) -> _TruckLoad | None:
    """Rebuild a load from a stop sequence; None if any stop is infeasible.

    pickup_order_ids: when set, only those orders divert via origin (mid-day new
    pickup). When None, morning default applies (pickup on the first stop only).
    live: False for fast search; True for final HERE ETAs / polylines.
    """
    origin_place = start_place or _depot_place(truck, driver)
    load = _TruckLoad(
        truck=truck,
        current_place=origin_place,
        current_time_min=float(start_time_min if start_time_min is not None else 0.0),
        truck_at_start=bool(start_place),
    )
    # Map start = truck current (mid-day) or home depot (morning)
    start_coords = travel.geocode(origin_place)
    if start_coords:
        load.depot_lat = start_coords.lat
        load.depot_lng = start_coords.lng
        load.depot_label = origin_place
        load.path_points.append(MapPoint(lat=start_coords.lat, lng=start_coords.lng))
    locked: set[int] = set()
    for order in orders:
        if _equipment_compatible(order, truck) is not None:
            return None
        if _truck_delivery_compatible(order, truck) is not None:
            return None
        if _driver_compatible(order, truck, driver) is not None:
            return None
        placement, cap = _find_placement(order, load)
        if placement is None or cap is not None:
            return None
        need_pickup = None if pickup_order_ids is None else (order.id in pickup_order_ids)
        time_plan, time_reason = _simulate_time(
            order,
            load,
            driver,
            day,
            travel,
            need_pickup=need_pickup,
            live=live,
        )
        if time_plan is None or time_reason is not None:
            return None
        _commit_order(load, order, driver, placement, time_plan, locked, travel)
        if load.corridor == "unknown":
            load.corridor = travel.corridor(_dest_place(order), depot)
    return load


def _first_leg_minutes(
    load: _TruckLoad,
    travel: TravelProvider,
    depot_place: str,
) -> float:
    """Travel minutes from depot to the first delivery (empty-sooner signal)."""
    if not load.orders:
        return 0.0
    if load.route_stops:
        return float(load.route_stops[0].travel_min_from_prev)
    dest = _dest_place(load.orders[0])
    return float(travel.travel(depot_place, dest, live=False).minutes)


def _window_urgency_key(order: Order, day: date, driver: Driver) -> tuple:
    """Earlier / harder due windows first."""
    due_end, hard = effective_window_end_min(
        planning_date=day,
        service=order.service,
        appointment=order.appointment,
        delivery_window_start=order.delivery_window_start,
        delivery_window_end=order.delivery_window_end,
        driver_shift_end_min=driver.shift_end_min,
    )
    return (
        0 if hard else 1,
        due_end if due_end is not None else 24 * 60,
        order.ordno,
    )


def _sequence_key(
    load: _TruckLoad,
    travel: TravelProvider,
    depot_place: str,
    day: date,
    driver: Driver,
) -> tuple[int, float, float, float]:
    """Prefer fewer soft window misses, less lateness, short first leg, less drive."""
    soft_misses = 0
    lateness = 0.0
    for order, stop in zip(load.orders, load.route_stops):
        due_end, hard = effective_window_end_min(
            planning_date=day,
            service=order.service,
            appointment=order.appointment,
            delivery_window_start=order.delivery_window_start,
            delivery_window_end=order.delivery_window_end,
            driver_shift_end_min=driver.shift_end_min,
        )
        if due_end is not None and stop.eta_min > due_end:
            if hard:
                soft_misses += 100
            else:
                soft_misses += 1
                lateness += float(stop.eta_min - due_end)
    return (
        soft_misses,
        lateness,
        _first_leg_minutes(load, travel, depot_place),
        load.drive_minutes,
    )


def _optimize_stop_order(
    load: _TruckLoad,
    day: date,
    travel: TravelProvider,
    depot: str,
    *,
    start_place: str | None = None,
    start_time_min: float | None = None,
    pickup_order_ids: set[int] | None = None,
) -> _TruckLoad:
    """Nearest / window-urgency seeds + 2-opt; hard windows reject via rebuild."""
    if load.driver is None or len(load.orders) < 2:
        return load

    driver = load.driver
    from_place = start_place or _depot_place(load.truck, driver)
    greedy = list(load.orders)

    nearest = sorted(
        greedy,
        key=lambda o: (
            float(travel.travel(from_place, _dest_place(o), live=False).minutes),
            o.ordno,
        ),
    )
    by_window = sorted(greedy, key=lambda o: _window_urgency_key(o, day, driver))

    seeds: list[list[Order]] = [nearest, by_window, greedy]
    # Prefer servicing a mid-day new pickup early (origin diversion) as a seed
    if pickup_order_ids:
        pickups = [o for o in greedy if o.id in pickup_order_ids]
        rest = [o for o in greedy if o.id not in pickup_order_ids]
        if pickups:
            rest_nearest = sorted(
                rest,
                key=lambda o: (
                    float(
                        travel.travel(
                            _dest_place(pickups[0]), _dest_place(o), live=False
                        ).minutes
                    ),
                    o.ordno,
                ),
            )
            rest_window = sorted(rest, key=lambda o: _window_urgency_key(o, day, driver))
            seeds.insert(0, pickups + rest_nearest)
            seeds.insert(1, pickups + rest_window)

    # Stub loads (e.g. mid-day dispatch) may list orders without a built route —
    # use a sentinel so any feasible rebuild wins.
    working = list(greedy)
    if load.route_stops and len(load.route_stops) == len(load.orders):
        best = load
        best_key = _sequence_key(load, travel, from_place, day, driver)
    else:
        best = load
        best_key = (10**9, 10**9, 10**9, 10**9)

    def consider(candidate_orders: list[Order]) -> None:
        nonlocal best, best_key, working
        # Search with static travel; finalize winner with live below.
        rebuilt = _build_load_for_sequence(
            load.truck,
            driver,
            candidate_orders,
            day,
            travel,
            depot,
            start_place=start_place,
            start_time_min=start_time_min,
            pickup_order_ids=pickup_order_ids,
            live=False,
        )
        if rebuilt is None:
            return
        key = _sequence_key(rebuilt, travel, from_place, day, driver)
        if key < best_key:
            best = rebuilt
            best_key = key
            working = list(candidate_orders)

    for seed in seeds:
        consider(seed)

    # 2-opt neighborhood from the current best working sequence
    n = len(working)
    improved = True
    while improved:
        improved = False
        base = list(working)
        for i in range(n - 1):
            for j in range(i + 1, n):
                candidate = base[:i] + list(reversed(base[i : j + 1])) + base[j + 1 :]
                before = best_key
                consider(candidate)
                if best_key < before:
                    improved = True
                    break
            if improved:
                break

    if not working:
        return load

    # Rebuild winning sequence with live HERE + weather for ETAs / map path
    use_live = travel.mode == "live"
    finalized = _build_load_for_sequence(
        load.truck,
        driver,
        working,
        day,
        travel,
        depot,
        start_place=start_place,
        start_time_min=start_time_min,
        pickup_order_ids=pickup_order_ids,
        live=use_live,
    )
    if finalized is not None and finalized.route_stops and len(finalized.route_stops) == len(
        finalized.orders
    ):
        return finalized
    if best.route_stops and len(best.route_stops) == len(best.orders):
        # Live timing rebuild can fail (windows/hours) after static search —
        # keep the feasible static plan but still pull HERE road polylines for the map.
        if use_live:
            _enrich_load_map_path(
                best,
                travel,
                start_place=start_place,
                pickup_order_ids=pickup_order_ids,
            )
        return best
    return load


def _enrich_load_map_path(
    load: _TruckLoad,
    travel: TravelProvider,
    *,
    start_place: str | None,
    pickup_order_ids: set[int] | None,
) -> None:
    """Replace path_points / stop coords with live HERE shapes (map only)."""
    if load.driver is None or not load.orders:
        return
    origin = start_place or load.depot_label or _depot_place(load.truck, load.driver)
    path: list[MapPoint] = []
    start_coords = travel.geocode(origin)
    if start_coords:
        path.append(MapPoint(lat=start_coords.lat, lng=start_coords.lng))
        load.depot_lat = start_coords.lat
        load.depot_lng = start_coords.lng
        load.depot_label = origin
        if start_place:
            load.truck_at_start = True

    prev = origin
    for i, order in enumerate(load.orders):
        dest = _dest_place(order)
        if pickup_order_ids is not None:
            need_pickup = order.id in pickup_order_ids
        else:
            need_pickup = i == 0

        shape: list = []
        if need_pickup:
            pickup = _origin_place(order)
            leg1 = travel.travel(prev, pickup, live=True)
            leg2 = travel.travel(pickup, dest, live=True)
            if leg1.shape:
                shape.extend(leg1.shape)
            if leg2.shape:
                shape.extend(leg2.shape[1:] if shape else leg2.shape)
        else:
            leg = travel.travel(prev, dest, live=True)
            shape = list(leg.shape)

        for pt in shape:
            lat = float(getattr(pt, "lat", 0))
            lng = float(getattr(pt, "lng", 0))
            if not path or abs(path[-1].lat - lat) > 1e-5 or abs(path[-1].lng - lng) > 1e-5:
                path.append(MapPoint(lat=lat, lng=lng))

        if i < len(load.route_stops):
            coords = travel.geocode(dest)
            if coords:
                load.route_stops[i].lat = coords.lat
                load.route_stops[i].lng = coords.lng
            elif shape:
                load.route_stops[i].lat = float(shape[-1].lat)
                load.route_stops[i].lng = float(shape[-1].lng)

        prev = dest

    if path:
        load.path_points = path


def _build_assignment(load: _TruckLoad) -> TruckAssignment:
    _finalize_lifo_placements(load)
    return TruckAssignment(
        truck_id=load.truck.id,
        unit_number=load.truck.unit_number,
        driver_id=load.driver.id if load.driver else None,
        driver_name=load.driver.name if load.driver else None,
        driver_code=load.driver.code if load.driver else None,
        truck_status=load.truck.status,
        duty_minutes_used=load.duty_minutes,
        order_ids=[o.id for o in load.orders],
        order_ordnos=[o.ordno for o in load.orders],
        destinations=sorted({_dest_place(o) for o in load.orders}),
        usage=CapacityUsage(
            weight_lbs=load.used_weight,
            skid_spots=load.floor.floor_used,
            linear_feet=load.used_feet,
            remaining_weight_lbs=load.remaining_weight,
            remaining_skid_spots=load.remaining_skids,
            remaining_linear_feet=load.remaining_feet,
        ),
        rationales=load.rationales,
        placements=list(load.placements),
        max_skid_spots=float(load.truck.max_skid_spots),
        max_linear_feet=float(load.truck.max_linear_feet),
        max_interior_height_in=int(load.truck.max_interior_height_in),
        route=AssignmentRoute(
            stops=list(load.route_stops),
            total_distance_m=load.distance_m,
            total_drive_min=load.drive_minutes,
            corridor=load.corridor,
            path=list(load.path_points),
            depot_lat=load.depot_lat,
            depot_lng=load.depot_lng,
            depot_label=load.depot_label,
            truck_at_start=load.truck_at_start,
        ),
    )


def optimize_assignments(
    trucks: list[Truck],
    orders: list[Order],
    drivers: list[Driver],
    planning_date: date | None = None,
) -> OptimizeResponse:
    day = planning_date or utc_now_naive_fallback()
    travel = TravelProvider.create()
    depot = next(
        (t.home_terminal_city for t in trucks if t.home_terminal_city),
        "Toronto",
    )

    available_trucks = [t for t in trucks if t.status != TruckStatus.OUT_OF_SERVICE.value]
    pool = [
        d
        for d in drivers
        if d.status
        not in {DriverStatus.OFF.value, DriverStatus.OUT_OF_SERVICE.value}
    ]
    # Only trucks that have an assigned driver participate
    loads = [
        _TruckLoad(
            truck=t,
            current_place=t.home_terminal_city,
            current_time_min=0.0,
        )
        for t in available_trucks
        if _driver_for_truck(t, pool) is not None
    ]
    locked_driver_ids: set[int] = set()

    unassigned_candidates = [
        o
        for o in orders
        if o.status == OrderStatus.UNASSIGNED.value or o.assigned_truck_id is None
    ]

    by_corridor: dict[str, list[Order]] = defaultdict(list)
    for order in unassigned_candidates:
        corr = travel.corridor(_dest_place(order), depot)
        by_corridor[corr].append(order)

    corridor_groups = sorted(
        by_corridor.items(),
        key=lambda item: (-sum(o.weight_lbs for o in item[1]), item[0]),
    )

    assigned_ids: set[int] = set()
    unassigned: list[UnassignedOrder] = []

    for corr, group in corridor_groups:
        group_sorted = sorted(
            group,
            key=lambda o: (
                0 if o.appointment else 1,
                o.delivery_window_end.timestamp()
                if o.delivery_window_end is not None
                else 9e12,
                -o.weight_lbs,
                o.ordno,
            ),
        )
        for order in group_sorted:
            loads_sorted = sorted(
                loads,
                key=lambda ld: (
                    -corridor_affinity(ld.corridor if ld.orders else corr, corr),
                    ld.truck.unit_number,
                ),
            )
            ok = _try_assign_order(
                order,
                loads_sorted,
                pool,
                locked_driver_ids,
                day,
                travel,
                depot,
            )
            if ok:
                assigned_ids.add(order.id)
            else:
                unassigned.append(
                    UnassignedOrder(
                        order_id=order.id,
                        ordno=order.ordno,
                        reason=_best_unassigned_reason(
                            order, loads, pool, locked_driver_ids, day, travel
                        ),
                    )
                )

    # Per-truck stop order (static search) then live HERE refresh for ETAs / map
    for idx, load in enumerate(loads):
        if not load.orders or load.driver is None:
            continue
        if len(load.orders) >= 2:
            loads[idx] = _optimize_stop_order(load, day, travel, depot)
        elif travel.mode == "live":
            rebuilt = _build_load_for_sequence(
                load.truck,
                load.driver,
                list(load.orders),
                day,
                travel,
                depot,
                live=True,
            )
            if rebuilt is not None:
                loads[idx] = rebuilt

    assignments = [_build_assignment(load) for load in loads if load.orders]
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
