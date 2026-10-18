from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.database import get_db
from app.models import Driver, Order, Truck, User
from app.schemas import OrderCreate, OrderOut, OrderUpdate

router = APIRouter(prefix="/orders", tags=["orders"])


def _build_order(payload: OrderCreate) -> Order:
    return Order(
        ordno=payload.ordno,
        reference=payload.reference,
        origin_city=payload.origin_city,
        destination_city=payload.destination_city,
        origin_address=payload.origin_address,
        destination_address=payload.destination_address,
        weight_lbs=payload.weight_lbs,
        skid_spots=payload.skid_spots,
        linear_feet=payload.linear_feet,
        dim_weight=payload.dim_weight,
        pieces=payload.pieces,
        stackable=payload.stackable,
        height_in=payload.height_in,
        service=payload.service.value,
        equipment_required=payload.equipment_required.value,
        requires_liftgate=payload.requires_liftgate,
        residential=payload.residential,
        inside_delivery=payload.inside_delivery,
        appointment=payload.appointment,
        dangerous_goods=payload.dangerous_goods,
        heated=payload.heated,
        delivery_window_start=payload.delivery_window_start,
        delivery_window_end=payload.delivery_window_end,
        status=payload.status.value,
        assigned_truck_id=payload.assigned_truck_id,
        assigned_driver_id=payload.assigned_driver_id,
    )


@router.get("", response_model=list[OrderOut])
def list_orders(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> list[Order]:
    return db.query(Order).order_by(Order.ordno).all()


@router.post("", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
def create_order(
    payload: OrderCreate,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> Order:
    existing = db.query(Order).filter(Order.ordno == payload.ordno).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Order ordno already exists",
        )
    if payload.assigned_truck_id is not None:
        if db.query(Truck).filter(Truck.id == payload.assigned_truck_id).first() is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="assigned_truck_id does not exist",
            )
    if payload.assigned_driver_id is not None:
        if db.query(Driver).filter(Driver.id == payload.assigned_driver_id).first() is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="assigned_driver_id does not exist",
            )
    order = _build_order(payload)
    db.add(order)
    db.commit()
    db.refresh(order)
    return order


@router.get("/{order_id}", response_model=OrderOut)
def get_order(
    order_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> Order:
    order = db.query(Order).filter(Order.id == order_id).first()
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return order


@router.patch("/{order_id}", response_model=OrderOut)
def update_order(
    order_id: int,
    payload: OrderUpdate,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> Order:
    order = db.query(Order).filter(Order.id == order_id).first()
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")

    data = payload.model_dump(exclude_unset=True)
    if "ordno" in data:
        clash = (
            db.query(Order)
            .filter(Order.ordno == data["ordno"], Order.id != order_id)
            .first()
        )
        if clash is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Order ordno already exists",
            )
    if "assigned_truck_id" in data and data["assigned_truck_id"] is not None:
        if db.query(Truck).filter(Truck.id == data["assigned_truck_id"]).first() is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="assigned_truck_id does not exist",
            )
    if "assigned_driver_id" in data and data["assigned_driver_id"] is not None:
        if db.query(Driver).filter(Driver.id == data["assigned_driver_id"]).first() is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="assigned_driver_id does not exist",
            )

    for key, value in data.items():
        if hasattr(value, "value"):
            setattr(order, key, value.value)
        else:
            setattr(order, key, value)

    db.commit()
    db.refresh(order)
    return order


@router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_order(
    order_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> None:
    order = db.query(Order).filter(Order.id == order_id).first()
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    db.delete(order)
    db.commit()
