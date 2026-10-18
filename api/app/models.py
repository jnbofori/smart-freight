from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.enums import (
    DriverStatus,
    EquipmentRequired,
    LicenceClass,
    OrderService,
    OrderStatus,
    TrailerSizeClass,
    TruckStatus,
    VehicleClass,
)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class Driver(Base):
    __tablename__ = "drivers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=DriverStatus.AVAILABLE.value
    )
    licence_class: Mapped[str] = mapped_column(
        String(8), nullable=False, default=LicenceClass.DZ.value
    )
    can_dangerous_goods: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_heated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_liftgate_runs: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    shift_start_min: Mapped[int] = mapped_column(Integer, nullable=False, default=6 * 60)
    shift_end_min: Mapped[int] = mapped_column(Integer, nullable=False, default=18 * 60)
    max_duty_hours: Mapped[float] = mapped_column(Float, nullable=False, default=13.0)
    max_drive_hours: Mapped[float] = mapped_column(Float, nullable=False, default=13.0)
    home_terminal_city: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    truck_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("trucks.id"), nullable=False, unique=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    orders: Mapped[list["Order"]] = relationship("Order", back_populates="assigned_driver")
    truck: Mapped["Truck"] = relationship(
        "Truck", back_populates="drivers", foreign_keys=[truck_id]
    )


class Truck(Base):
    __tablename__ = "trucks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    unit_number: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    vehicle_class: Mapped[str] = mapped_column(
        String(32), nullable=False, default=VehicleClass.TRUCK.value
    )
    axle_count: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    max_weight_lbs: Mapped[int] = mapped_column(Integer, nullable=False)
    max_skid_spots: Mapped[int] = mapped_column(Integer, nullable=False)
    max_linear_feet: Mapped[int] = mapped_column(Integer, nullable=False)
    max_interior_height_in: Mapped[int] = mapped_column(Integer, nullable=False, default=110)
    has_trailer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    trailer_unit: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    trailer_size_class: Mapped[str] = mapped_column(
        String(16), nullable=False, default=TrailerSizeClass.NONE.value
    )
    has_liftgate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    has_dock_height: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    heated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    home_terminal_city: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    # Mid-day demo position; empty → treat as home_terminal_city
    current_address: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    current_lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    current_lng: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=TruckStatus.AVAILABLE.value
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    orders: Mapped[list["Order"]] = relationship("Order", back_populates="assigned_truck")
    drivers: Mapped[list["Driver"]] = relationship(
        "Driver",
        back_populates="truck",
        foreign_keys="Driver.truck_id",
    )


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    ordno: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    reference: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    origin_city: Mapped[str] = mapped_column(String(128), nullable=False)
    destination_city: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    origin_address: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    destination_address: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    weight_lbs: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    skid_spots: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    linear_feet: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    dim_weight: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pieces: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    stackable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    height_in: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    service: Mapped[str] = mapped_column(
        String(64), nullable=False, default=OrderService.LTL.value
    )
    equipment_required: Mapped[str] = mapped_column(
        String(32), nullable=False, default=EquipmentRequired.ANY.value
    )
    requires_liftgate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    residential: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    inside_delivery: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    appointment: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    dangerous_goods: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    heated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    delivery_window_start: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delivery_window_end: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=OrderStatus.UNASSIGNED.value
    )
    assigned_truck_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("trucks.id"), nullable=True
    )
    assigned_driver_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("drivers.id"), nullable=True
    )
    # 0-based delivery stop order from last persisted optimize/dispatch plan
    stop_seq: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    assigned_truck: Mapped[Optional["Truck"]] = relationship("Truck", back_populates="orders")
    assigned_driver: Mapped[Optional["Driver"]] = relationship("Driver", back_populates="orders")
