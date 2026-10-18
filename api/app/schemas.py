from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

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


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    full_name: str
    created_at: datetime


# --- Drivers ---


class DriverBase(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=255)
    status: DriverStatus = DriverStatus.AVAILABLE
    licence_class: LicenceClass = LicenceClass.DZ
    can_dangerous_goods: bool = False
    can_heated: bool = False
    can_liftgate_runs: bool = True
    shift_start_min: int = Field(default=6 * 60, ge=0, le=24 * 60)
    shift_end_min: int = Field(default=20 * 60, ge=0, le=24 * 60)
    max_duty_hours: float = Field(default=13.0, gt=0, le=24)
    max_drive_hours: float = Field(default=13.0, gt=0, le=24)
    home_terminal_city: str = ""
    truck_id: int


class DriverCreate(DriverBase):
    pass


class DriverUpdate(BaseModel):
    code: Optional[str] = Field(default=None, min_length=1, max_length=32)
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    status: Optional[DriverStatus] = None
    licence_class: Optional[LicenceClass] = None
    can_dangerous_goods: Optional[bool] = None
    can_heated: Optional[bool] = None
    can_liftgate_runs: Optional[bool] = None
    shift_start_min: Optional[int] = Field(default=None, ge=0, le=24 * 60)
    shift_end_min: Optional[int] = Field(default=None, ge=0, le=24 * 60)
    max_duty_hours: Optional[float] = Field(default=None, gt=0, le=24)
    max_drive_hours: Optional[float] = Field(default=None, gt=0, le=24)
    home_terminal_city: Optional[str] = None
    truck_id: Optional[int] = None


class DriverOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    name: str
    status: str
    licence_class: str
    can_dangerous_goods: bool
    can_heated: bool
    can_liftgate_runs: bool
    shift_start_min: int
    shift_end_min: int
    max_duty_hours: float
    max_drive_hours: float
    home_terminal_city: str
    truck_id: int
    created_at: datetime


# --- Trucks ---


class TruckBase(BaseModel):
    unit_number: str = Field(min_length=1, max_length=64)
    vehicle_class: VehicleClass = VehicleClass.TRUCK
    axle_count: int = Field(ge=2, le=8, default=2)
    max_weight_lbs: Optional[int] = Field(default=None, ge=1)
    max_skid_spots: Optional[int] = Field(default=None, ge=0)
    max_linear_feet: Optional[int] = Field(default=None, ge=0)
    max_interior_height_in: Optional[int] = Field(default=None, ge=1)
    has_trailer: bool = False
    trailer_unit: Optional[str] = None
    trailer_size_class: TrailerSizeClass = TrailerSizeClass.NONE
    has_liftgate: bool = False
    has_dock_height: bool = True
    heated: bool = False
    home_terminal_city: str = ""
    current_address: str = ""
    current_lat: Optional[float] = None
    current_lng: Optional[float] = None
    status: TruckStatus = TruckStatus.AVAILABLE


class TruckCreate(TruckBase):
    pass


class TruckUpdate(BaseModel):
    unit_number: Optional[str] = Field(default=None, min_length=1, max_length=64)
    vehicle_class: Optional[VehicleClass] = None
    axle_count: Optional[int] = Field(default=None, ge=2, le=8)
    max_weight_lbs: Optional[int] = Field(default=None, ge=1)
    max_skid_spots: Optional[int] = Field(default=None, ge=0)
    max_linear_feet: Optional[int] = Field(default=None, ge=0)
    max_interior_height_in: Optional[int] = Field(default=None, ge=1)
    has_trailer: Optional[bool] = None
    trailer_unit: Optional[str] = None
    trailer_size_class: Optional[TrailerSizeClass] = None
    has_liftgate: Optional[bool] = None
    has_dock_height: Optional[bool] = None
    heated: Optional[bool] = None
    home_terminal_city: Optional[str] = None
    current_address: Optional[str] = None
    current_lat: Optional[float] = None
    current_lng: Optional[float] = None
    status: Optional[TruckStatus] = None


class TruckOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    unit_number: str
    vehicle_class: str
    axle_count: int
    max_weight_lbs: int
    max_skid_spots: int
    max_linear_feet: int
    max_interior_height_in: int
    has_trailer: bool
    trailer_unit: Optional[str]
    trailer_size_class: str
    has_liftgate: bool
    has_dock_height: bool
    heated: bool
    home_terminal_city: str
    current_address: str
    current_lat: Optional[float]
    current_lng: Optional[float]
    status: str
    created_at: datetime


# --- Orders ---


class OrderBase(BaseModel):
    ordno: str = Field(min_length=1, max_length=64)
    reference: Optional[str] = None
    origin_city: str = Field(min_length=1)
    destination_city: str = Field(min_length=1)
    origin_address: str = Field(min_length=1, max_length=255)
    destination_address: str = Field(min_length=1, max_length=255)
    weight_lbs: float = Field(ge=0, default=0)
    skid_spots: float = Field(ge=0, default=0)
    linear_feet: float = Field(ge=0, default=0)
    dim_weight: Optional[float] = Field(default=None, ge=0)
    pieces: int = Field(ge=1, default=1)
    stackable: bool = False
    height_in: Optional[float] = Field(default=None, ge=0)
    service: OrderService = OrderService.LTL
    equipment_required: EquipmentRequired = EquipmentRequired.ANY
    requires_liftgate: bool = False
    residential: bool = False
    inside_delivery: bool = False
    appointment: bool = False
    dangerous_goods: bool = False
    heated: bool = False
    delivery_window_start: Optional[datetime] = None
    delivery_window_end: Optional[datetime] = None
    status: OrderStatus = OrderStatus.UNASSIGNED
    assigned_truck_id: Optional[int] = None
    assigned_driver_id: Optional[int] = None


class OrderCreate(OrderBase):
    pass


class OrderUpdate(BaseModel):
    ordno: Optional[str] = Field(default=None, min_length=1, max_length=64)
    reference: Optional[str] = None
    origin_city: Optional[str] = None
    destination_city: Optional[str] = None
    origin_address: Optional[str] = Field(default=None, min_length=1, max_length=255)
    destination_address: Optional[str] = Field(default=None, min_length=1, max_length=255)
    weight_lbs: Optional[float] = Field(default=None, ge=0)
    skid_spots: Optional[float] = Field(default=None, ge=0)
    linear_feet: Optional[float] = Field(default=None, ge=0)
    dim_weight: Optional[float] = Field(default=None, ge=0)
    pieces: Optional[int] = Field(default=None, ge=1)
    stackable: Optional[bool] = None
    height_in: Optional[float] = Field(default=None, ge=0)
    service: Optional[OrderService] = None
    equipment_required: Optional[EquipmentRequired] = None
    requires_liftgate: Optional[bool] = None
    residential: Optional[bool] = None
    inside_delivery: Optional[bool] = None
    appointment: Optional[bool] = None
    dangerous_goods: Optional[bool] = None
    heated: Optional[bool] = None
    delivery_window_start: Optional[datetime] = None
    delivery_window_end: Optional[datetime] = None
    status: Optional[OrderStatus] = None
    assigned_truck_id: Optional[int] = None
    assigned_driver_id: Optional[int] = None


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ordno: str
    reference: Optional[str]
    origin_city: str
    destination_city: str
    origin_address: str
    destination_address: str
    weight_lbs: float
    skid_spots: float
    linear_feet: float
    dim_weight: Optional[float]
    pieces: int
    stackable: bool
    height_in: Optional[float]
    service: str
    equipment_required: str
    requires_liftgate: bool
    residential: bool
    inside_delivery: bool
    appointment: bool
    dangerous_goods: bool
    heated: bool
    delivery_window_start: Optional[datetime]
    delivery_window_end: Optional[datetime]
    status: str
    assigned_truck_id: Optional[int]
    assigned_driver_id: Optional[int]
    stop_seq: Optional[int] = None
    created_at: datetime


# --- Optimize ---


class OptimizeRequest(BaseModel):
    persist: bool = False
    planning_date: Optional[date] = None


class CapacityUsage(BaseModel):
    weight_lbs: float
    skid_spots: float
    linear_feet: float
    remaining_weight_lbs: float
    remaining_skid_spots: float
    remaining_linear_feet: float


class LoadPlacement(BaseModel):
    order_id: int
    ordno: str
    column_index: int
    layer: int
    floor_spots: float
    skid_spots: float
    linear_feet: float
    height_in: Optional[float] = None
    stackable: bool
    stacked: bool
    stop_seq: int = 0  # 0 = first delivery (door / LIFO unload)
    load_seq: int = 0  # 0 = loaded first (nose); highest = at door


class RouteStop(BaseModel):
    order_id: int
    ordno: str
    seq: int
    destination_city: str
    destination_address: str = ""
    eta_min: float
    travel_min_from_prev: float
    lat: Optional[float] = None
    lng: Optional[float] = None
    weather_note: str = ""


class MapPoint(BaseModel):
    lat: float
    lng: float


class AssignmentRoute(BaseModel):
    stops: list[RouteStop] = []
    total_distance_m: float = 0
    total_drive_min: float = 0
    corridor: str = "unknown"
    # Road path (depot → stops) for map; falls back to stop markers if empty
    path: list[MapPoint] = []
    depot_lat: Optional[float] = None
    depot_lng: Optional[float] = None
    depot_label: str = ""
    # True when depot_* is the truck's mid-day current place (not home terminal)
    truck_at_start: bool = False


class TruckAssignment(BaseModel):
    truck_id: int
    unit_number: str
    driver_id: Optional[int] = None
    driver_name: Optional[str] = None
    driver_code: Optional[str] = None
    truck_status: Optional[str] = None
    duty_minutes_used: float = 0
    order_ids: list[int]
    order_ordnos: list[str]
    destinations: list[str]
    usage: CapacityUsage
    rationales: list[str]
    reasoning_summary: str = ""
    placements: list[LoadPlacement] = []
    max_skid_spots: float = 0
    max_linear_feet: float = 0
    max_interior_height_in: int = 84
    route: Optional[AssignmentRoute] = None


class UnassignedOrder(BaseModel):
    order_id: int
    ordno: str
    reason: str


class OptimizeResponse(BaseModel):
    assignments: list[TruckAssignment]
    unassigned: list[UnassignedOrder]
    summary: dict[str, int]
    planning_date: date
    routing_mode: str = "static"  # static | live
    weather_summary: str = ""
    unassigned_summary: str = ""


class RouteHistoryStop(BaseModel):
    seq: int = 0
    ordno: str = ""
    destination: str = ""
    eta_min: float = 0


class RouteHistorySnapshot(BaseModel):
    truck_id: int = 0
    unit_number: str = ""
    driver_name: str = ""
    driver_code: str = ""
    order_ordnos: list[str] = []
    destinations: list[str] = []
    corridor: str = ""
    reasoning_summary: str = ""
    stops: list[RouteHistoryStop] = []


class RouteHistoryEntryOut(BaseModel):
    id: int
    created_at: datetime
    event_type: str
    note: str = ""
    truck_id: int
    unit_number: str
    snapshot: RouteHistorySnapshot


class RouteHistoryListResponse(BaseModel):
    truck_id: Optional[int] = None
    unit_number: str = ""
    entries: list[RouteHistoryEntryOut]


class SimulatedTruck(BaseModel):
    truck_id: int
    unit_number: str
    delivered_order_ids: list[int]
    delivered_ordnos: list[str]
    remaining_order_ids: list[int]
    current_address: str
    current_lat: Optional[float] = None
    current_lng: Optional[float] = None
    # Road path from current place through remaining stops (HERE when live)
    path: list[MapPoint] = []


class SimulateResponse(BaseModel):
    trucks_moved: list[SimulatedTruck]
    summary: dict[str, int]


class DispatchRequest(BaseModel):
    order_id: int
    persist: bool = True


class DispatchReject(BaseModel):
    truck_id: int
    unit_number: str
    reason: str


class DispatchResponse(BaseModel):
    order_id: int
    ordno: str
    chosen_truck_id: Optional[int] = None
    chosen_unit_number: Optional[str] = None
    travel_min_to_pickup: Optional[float] = None
    reason: str = ""
    rejects: list[DispatchReject] = []
    assignment: Optional[TruckAssignment] = None


class BreakdownReportRequest(BaseModel):
    truck_id: int


class BreakdownApproveRequest(BaseModel):
    truck_id: int
    rescue_truck_id: int
    persist: bool = True


class BreakdownReportResponse(BaseModel):
    broken_truck_id: int
    broken_unit_number: str
    broken_driver_name: Optional[str] = None
    broken_driver_code: Optional[str] = None
    breakdown_address: str
    breakdown_lat: Optional[float] = None
    breakdown_lng: Optional[float] = None
    delivered_order_ids: list[int] = []
    delivered_ordnos: list[str] = []
    remaining_order_ids: list[int] = []
    remaining_ordnos: list[str] = []
    recommended_truck_id: Optional[int] = None
    recommended_unit_number: Optional[str] = None
    travel_min_to_breakdown: Optional[float] = None
    reason: str = ""
    rejects: list[DispatchReject] = []
    preview_assignment: Optional[TruckAssignment] = None


class BreakdownApproveResponse(BaseModel):
    broken_truck_id: int
    broken_unit_number: str
    rescue_truck_id: Optional[int] = None
    rescue_unit_number: Optional[str] = None
    travel_min_to_breakdown: Optional[float] = None
    reason: str = ""
    rejects: list[DispatchReject] = []
    assignment: Optional[TruckAssignment] = None
    transferred_order_ids: list[int] = []
    transferred_ordnos: list[str] = []


class CancelRequest(BaseModel):
    order_id: int
    persist: bool = True


class CancelResponse(BaseModel):
    cancelled_order_id: int
    ordno: str
    truck_id: Optional[int] = None
    unit_number: Optional[str] = None
    reason: str = ""
    assignment: Optional[TruckAssignment] = None
    remaining_order_ids: list[int] = []
    remaining_ordnos: list[str] = []


class DriverAbsenceRequest(BaseModel):
    driver_id: int
    persist: bool = True


class DriverAbsenceResponse(BaseModel):
    driver_id: int
    driver_name: str
    driver_code: str
    truck_id: Optional[int] = None
    unit_number: Optional[str] = None
    orders_freed: int = 0
    reason: str = ""
    plan: Optional[OptimizeResponse] = None
