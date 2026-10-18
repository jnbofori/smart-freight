from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.database import get_db
from app.enums import OrderStatus, TrailerSizeClass
from app.models import Order, Truck, User
from app.schemas import TruckCreate, TruckOut, TruckUpdate
from app.services.capacity import resolve_truck_capacity

router = APIRouter(prefix="/trucks", tags=["trucks"])


def _build_truck(payload: TruckCreate) -> Truck:
    weight, skids, feet, height = resolve_truck_capacity(
        payload.vehicle_class.value,
        payload.axle_count,
        payload.has_trailer,
        payload.trailer_size_class.value,
        payload.max_weight_lbs,
        payload.max_skid_spots,
        payload.max_linear_feet,
        payload.max_interior_height_in,
    )
    return Truck(
        unit_number=payload.unit_number,
        vehicle_class=payload.vehicle_class.value,
        axle_count=payload.axle_count,
        max_weight_lbs=weight,
        max_skid_spots=skids,
        max_linear_feet=feet,
        max_interior_height_in=height,
        has_trailer=payload.has_trailer,
        trailer_unit=payload.trailer_unit,
        trailer_size_class=payload.trailer_size_class.value,
        has_liftgate=payload.has_liftgate,
        has_dock_height=payload.has_dock_height,
        heated=payload.heated,
        home_terminal_city=payload.home_terminal_city,
        current_address=payload.current_address or payload.home_terminal_city,
        current_lat=payload.current_lat,
        current_lng=payload.current_lng,
        status=payload.status.value,
    )


@router.get("", response_model=list[TruckOut])
def list_trucks(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> list[Truck]:
    return db.query(Truck).order_by(Truck.unit_number).all()


@router.post("", response_model=TruckOut, status_code=status.HTTP_201_CREATED)
def create_truck(
    payload: TruckCreate,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> Truck:
    existing = db.query(Truck).filter(Truck.unit_number == payload.unit_number).first()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Truck unit_number already exists",
        )
    truck = _build_truck(payload)
    db.add(truck)
    db.commit()
    db.refresh(truck)
    return truck


@router.get("/{truck_id}", response_model=TruckOut)
def get_truck(
    truck_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> Truck:
    truck = db.query(Truck).filter(Truck.id == truck_id).first()
    if truck is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Truck not found")
    return truck


@router.patch("/{truck_id}", response_model=TruckOut)
def update_truck(
    truck_id: int,
    payload: TruckUpdate,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> Truck:
    truck = db.query(Truck).filter(Truck.id == truck_id).first()
    if truck is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Truck not found")

    data = payload.model_dump(exclude_unset=True)
    if "unit_number" in data:
        clash = (
            db.query(Truck)
            .filter(Truck.unit_number == data["unit_number"], Truck.id != truck_id)
            .first()
        )
        if clash is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Truck unit_number already exists",
            )

    for key, value in data.items():
        if hasattr(value, "value"):
            setattr(truck, key, value.value)
        else:
            setattr(truck, key, value)

    structural_keys = {"vehicle_class", "axle_count", "has_trailer", "trailer_size_class"}
    explicit_caps = {
        "max_weight_lbs",
        "max_skid_spots",
        "max_linear_feet",
        "max_interior_height_in",
    }
    if structural_keys & data.keys() or explicit_caps & data.keys():
        weight, skids, feet, height = resolve_truck_capacity(
            truck.vehicle_class,
            truck.axle_count,
            truck.has_trailer,
            truck.trailer_size_class or TrailerSizeClass.NONE.value,
            data.get("max_weight_lbs") if "max_weight_lbs" in data else (
                None if structural_keys & data.keys() else truck.max_weight_lbs
            ),
            data.get("max_skid_spots") if "max_skid_spots" in data else (
                None if structural_keys & data.keys() else truck.max_skid_spots
            ),
            data.get("max_linear_feet") if "max_linear_feet" in data else (
                None if structural_keys & data.keys() else truck.max_linear_feet
            ),
            data.get("max_interior_height_in") if "max_interior_height_in" in data else (
                None if structural_keys & data.keys() else truck.max_interior_height_in
            ),
        )
        truck.max_weight_lbs = weight
        truck.max_skid_spots = skids
        truck.max_linear_feet = feet
        truck.max_interior_height_in = height

    db.commit()
    db.refresh(truck)
    return truck


@router.delete("/{truck_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_truck(
    truck_id: int,
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> None:
    truck = db.query(Truck).filter(Truck.id == truck_id).first()
    if truck is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Truck not found")
    for order in db.query(Order).filter(Order.assigned_truck_id == truck_id).all():
        order.assigned_truck_id = None
        order.status = OrderStatus.UNASSIGNED.value
    db.delete(truck)
    db.commit()
