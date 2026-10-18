from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.database import get_db
from app.enums import DriverStatus, OrderStatus, TruckStatus
from app.models import Driver, Order, Truck, User
from app.schemas import (
    BreakdownApproveRequest,
    BreakdownApproveResponse,
    BreakdownReportRequest,
    BreakdownReportResponse,
    CancelRequest,
    CancelResponse,
    DispatchRequest,
    DispatchResponse,
    DriverAbsenceRequest,
    DriverAbsenceResponse,
    OptimizeRequest,
    OptimizeResponse,
    SimulateResponse,
)
from app.services.absence import report_driver_absence
from app.services.breakdown import approve_breakdown, report_breakdown
from app.services.cancel import cancel_order
from app.services.dispatch import dispatch_order
from app.services.optimizer import optimize_assignments
from app.services.plan import load_persisted_plan
from app.services.plan_persist import persist_optimize_result
from app.services.simulate import simulate_midday
from app.services.travel import utc_now_naive_fallback

router = APIRouter(prefix="/optimize", tags=["optimize"])


@router.get("", response_model=OptimizeResponse)
def get_optimize_plan(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> OptimizeResponse:
    """Return the persisted plan reconstructed from assigned orders (empty if none)."""
    return load_persisted_plan(db)


@router.post("", response_model=OptimizeResponse)
def run_optimize(
    payload: OptimizeRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> OptimizeResponse:
    trucks = db.query(Truck).all()
    drivers = db.query(Driver).all()
    orders = (
        db.query(Order)
        .filter(Order.status == OrderStatus.UNASSIGNED.value)
        .all()
    )
    planning_date = payload.planning_date or utc_now_naive_fallback()
    result = optimize_assignments(trucks, orders, drivers, planning_date)

    if payload.persist:
        persist_optimize_result(db, result, trucks, drivers, orders)

    return result


@router.post("/simulate", response_model=SimulateResponse)
def run_simulate(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> SimulateResponse:
    assigned_count = (
        db.query(Order)
        .filter(Order.status == OrderStatus.ASSIGNED.value)
        .count()
    )
    if assigned_count == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No assigned orders — run & persist a morning plan first",
        )
    return simulate_midday(db)


@router.post("/dispatch", response_model=DispatchResponse)
def run_dispatch(
    payload: DispatchRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> DispatchResponse:
    result = dispatch_order(db, payload.order_id, persist=payload.persist)
    if result.ordno == "" and result.reason == "order not found":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )
    return result


@router.post("/breakdown", response_model=BreakdownReportResponse)
def run_breakdown_report(
    payload: BreakdownReportRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> BreakdownReportResponse:
    result = report_breakdown(db, payload.truck_id)
    if result.broken_unit_number == "" and result.reason == "truck not found":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Truck not found",
        )
    if result.reason.startswith("no remaining"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.reason,
        )
    return result


@router.post("/breakdown/approve", response_model=BreakdownApproveResponse)
def run_breakdown_approve(
    payload: BreakdownApproveRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> BreakdownApproveResponse:
    result = approve_breakdown(
        db,
        payload.truck_id,
        payload.rescue_truck_id,
        persist=payload.persist,
    )
    if result.broken_unit_number == "" and result.reason == "truck not found":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Truck not found",
        )
    if "not found" in result.reason and result.rescue_truck_id is None:
        if "rescue truck not found" in result.reason:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=result.reason,
            )
    return result


@router.post("/cancel", response_model=CancelResponse)
def run_cancel(
    payload: CancelRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> CancelResponse:
    result = cancel_order(db, payload.order_id, persist=payload.persist)
    if result.ordno == "" and result.reason == "order not found":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )
    if result.reason.startswith("order status is"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.reason,
        )
    return result


@router.post("/driver-absence", response_model=DriverAbsenceResponse)
def run_driver_absence(
    payload: DriverAbsenceRequest,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> DriverAbsenceResponse:
    result = report_driver_absence(db, payload.driver_id, persist=payload.persist)
    if result.driver_name == "" and result.reason == "driver not found":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver not found",
        )
    if "cannot mark absent" in result.reason:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result.reason,
        )
    return result


@router.post("/reset", status_code=status.HTTP_204_NO_CONTENT)
def reset_assignments(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> None:
    orders = (
        db.query(Order)
        .filter(
            Order.status.in_(
                [
                    OrderStatus.ASSIGNED.value,
                    OrderStatus.DELIVERED.value,
                    OrderStatus.CANCELLED.value,
                ]
            )
        )
        .all()
    )
    for order in orders:
        order.assigned_truck_id = None
        order.assigned_driver_id = None
        order.stop_seq = None
        order.status = OrderStatus.UNASSIGNED.value

    # Assigned + demo OOS trucks back to available
    trucks = (
        db.query(Truck)
        .filter(
            Truck.status.in_(
                [TruckStatus.ASSIGNED.value, TruckStatus.OUT_OF_SERVICE.value]
            )
        )
        .all()
    )
    for truck in trucks:
        truck.status = TruckStatus.AVAILABLE.value

    for truck in db.query(Truck).all():
        truck.current_address = truck.home_terminal_city or ""
        truck.current_lat = None
        truck.current_lng = None

    drivers = (
        db.query(Driver)
        .filter(
            Driver.status.in_(
                [
                    DriverStatus.ASSIGNED.value,
                    DriverStatus.OUT_OF_SERVICE.value,
                    DriverStatus.OFF.value,
                ]
            )
        )
        .all()
    )
    for driver in drivers:
        driver.status = DriverStatus.AVAILABLE.value

    db.commit()
