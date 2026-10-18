"""Morning driver no-show: mark OFF and fully replan assigned work."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.enums import DriverStatus, OrderStatus, TruckStatus
from app.models import Driver, Order, Truck
from app.schemas import DriverAbsenceResponse
from app.services.optimizer import optimize_assignments
from app.services.llm_summarize import summarize_optimize_result
from app.services.plan_persist import persist_optimize_result
from app.services.travel import utc_now_naive_fallback


def report_driver_absence(
    db: Session,
    driver_id: int,
    *,
    persist: bool = True,
) -> DriverAbsenceResponse:
    driver = db.query(Driver).filter(Driver.id == driver_id).first()
    if driver is None:
        return DriverAbsenceResponse(
            driver_id=driver_id,
            driver_name="",
            driver_code="",
            reason="driver not found",
        )
    if driver.status in {
        DriverStatus.OFF.value,
        DriverStatus.OUT_OF_SERVICE.value,
    }:
        return DriverAbsenceResponse(
            driver_id=driver.id,
            driver_name=driver.name,
            driver_code=driver.code,
            truck_id=driver.truck_id,
            reason=f"driver status is {driver.status}; cannot mark absent",
        )

    truck = db.query(Truck).filter(Truck.id == driver.truck_id).first()
    unit = truck.unit_number if truck is not None else None

    assigned = (
        db.query(Order)
        .filter(Order.status == OrderStatus.ASSIGNED.value)
        .all()
    )
    orders_freed = len(assigned)

    driver.status = DriverStatus.OFF.value

    for order in assigned:
        order.assigned_truck_id = None
        order.assigned_driver_id = None
        order.stop_seq = None
        order.status = OrderStatus.UNASSIGNED.value

    trucks = db.query(Truck).all()
    for t in trucks:
        if t.status == TruckStatus.ASSIGNED.value:
            t.status = TruckStatus.AVAILABLE.value

    drivers = db.query(Driver).all()
    for d in drivers:
        if d.id == driver.id:
            continue
        if d.status == DriverStatus.ASSIGNED.value:
            d.status = DriverStatus.AVAILABLE.value

    if persist:
        db.flush()

    unassigned = (
        db.query(Order)
        .filter(Order.status == OrderStatus.UNASSIGNED.value)
        .all()
    )
    # Refresh collections after status changes
    trucks = db.query(Truck).all()
    drivers = db.query(Driver).all()
    day = utc_now_naive_fallback()
    plan = summarize_optimize_result(
        optimize_assignments(trucks, unassigned, drivers, day)
    )

    if persist:
        persist_optimize_result(
            db,
            plan,
            trucks,
            drivers,
            unassigned,
            commit=True,
            event_type="absence",
            history_note=(
                f"Driver {driver.name} ({driver.code}) absent; "
                f"freed {orders_freed} order(s)"
            ),
        )

    assigned_count = plan.summary.get("orders_assigned", 0)
    reason = (
        f"Driver {driver.name} ({driver.code}) marked absent; "
        f"freed {orders_freed} assigned order(s); "
        f"replanned {assigned_count} order(s)"
    )
    return DriverAbsenceResponse(
        driver_id=driver.id,
        driver_name=driver.name,
        driver_code=driver.code,
        truck_id=driver.truck_id,
        unit_number=unit,
        orders_freed=orders_freed,
        reason=reason,
        plan=plan,
    )
