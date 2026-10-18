from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.database import get_db
from app.enums import OrderStatus
from app.models import Driver, Order, Truck, User
from app.schemas import DriverCreate, DriverOut, DriverUpdate

router = APIRouter(prefix="/drivers", tags=["drivers"])


def _ensure_truck_available(
    db: Session,
    truck_id: int,
    *,
    exclude_driver_id: int | None = None,
) -> None:
    if db.query(Truck).filter(Truck.id == truck_id).first() is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="truck_id does not exist",
        )
    q = db.query(Driver).filter(Driver.truck_id == truck_id)
    if exclude_driver_id is not None:
        q = q.filter(Driver.id != exclude_driver_id)
    if q.first() is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="truck_id already assigned to another driver",
        )


def _build_driver(payload: DriverCreate) -> Driver:
    return Driver(
        code=payload.code,
        name=payload.name,
        status=payload.status.value,
        licence_class=payload.licence_class.value,
        can_dangerous_goods=payload.can_dangerous_goods,
        can_heated=payload.can_heated,
        can_liftgate_runs=payload.can_liftgate_runs,
        shift_start_min=payload.shift_start_min,
        shift_end_min=payload.shift_end_min,
        max_duty_hours=payload.max_duty_hours,
        max_drive_hours=payload.max_drive_hours,
        home_terminal_city=payload.home_terminal_city,
        truck_id=payload.truck_id,
    )


@router.get("", response_model=list[DriverOut])
def list_drivers(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> list[Driver]:
    return db.query(Driver).order_by(Driver.code).all()


@router.post("", response_model=DriverOut, status_code=status.HTTP_201_CREATED)
def create_driver(
    payload: DriverCreate,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> Driver:
    if db.query(Driver).filter(Driver.code == payload.code).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Driver code already exists")
    _ensure_truck_available(db, payload.truck_id)
    driver = _build_driver(payload)
    db.add(driver)
    db.commit()
    db.refresh(driver)
    return driver


@router.get("/{driver_id}", response_model=DriverOut)
def get_driver(
    driver_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> Driver:
    driver = db.query(Driver).filter(Driver.id == driver_id).first()
    if driver is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Driver not found")
    return driver


@router.patch("/{driver_id}", response_model=DriverOut)
def update_driver(
    driver_id: int,
    payload: DriverUpdate,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> Driver:
    driver = db.query(Driver).filter(Driver.id == driver_id).first()
    if driver is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Driver not found")

    data = payload.model_dump(exclude_unset=True)
    if "code" in data:
        clash = (
            db.query(Driver)
            .filter(Driver.code == data["code"], Driver.id != driver_id)
            .first()
        )
        if clash is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Driver code already exists",
            )
    if "truck_id" in data:
        if data["truck_id"] is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="truck_id is required",
            )
        _ensure_truck_available(db, data["truck_id"], exclude_driver_id=driver_id)

    for key, value in data.items():
        if hasattr(value, "value"):
            setattr(driver, key, value.value)
        else:
            setattr(driver, key, value)

    db.commit()
    db.refresh(driver)
    return driver


@router.delete("/{driver_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_driver(
    driver_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> None:
    driver = db.query(Driver).filter(Driver.id == driver_id).first()
    if driver is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Driver not found")
    for order in db.query(Order).filter(Order.assigned_driver_id == driver_id).all():
        order.assigned_driver_id = None
        order.status = OrderStatus.UNASSIGNED.value
        order.assigned_truck_id = None
    db.delete(driver)
    db.commit()
