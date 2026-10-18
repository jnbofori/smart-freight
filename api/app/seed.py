import json
import os
from datetime import datetime, time
from pathlib import Path

from sqlalchemy.orm import Session

from app.auth.security import hash_password
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
from app.models import Driver, HosStatusLog, Order, Truck, User
from app.services.capacity import resolve_truck_capacity
from app.services.travel import TORONTO, utc_now_naive_fallback

DEMO_EMAIL = "dispatcher@transontario.ca"
DEMO_PASSWORD = "changeme"
DEMO_FULL_NAME = "Demo Dispatcher"

# Elite extract: real driver names + stop addresses only (not full fleet rebuild)
ELITE_SEED_PATH = Path(__file__).resolve().parent / "data" / "elite_seed.json"


def _load_elite() -> dict:
    if not ELITE_SEED_PATH.exists():
        return {"depot": {}, "drivers": [], "addresses": []}
    return json.loads(ELITE_SEED_PATH.read_text(encoding="utf-8"))


def _elite_driver_name(code: str, fallback: str) -> str:
    for d in _load_elite().get("drivers", []):
        if str(d.get("code")) == str(code):
            return d.get("name") or fallback
    return fallback


def _elite_addr(ordno: str) -> dict | None:
    for a in _load_elite().get("addresses", []):
        if str(a.get("ordno")) == str(ordno):
            return a
    return None


def clear_fleet_data(db: Session) -> None:
    try:
        db.query(HosStatusLog).delete()
    except Exception:
        db.rollback()
    db.query(Order).delete()
    db.query(Driver).delete()
    db.query(Truck).delete()
    db.commit()


def _day_dt(hour: int, minute: int = 0) -> datetime:
    d = utc_now_naive_fallback()
    return datetime.combine(d, time(hour, minute), tzinfo=TORONTO)


def seed_demo_user(db: Session) -> None:
    existing = db.query(User).filter(User.email == DEMO_EMAIL).first()
    if existing is not None:
        return
    db.add(
        User(
            email=DEMO_EMAIL,
            hashed_password=hash_password(DEMO_PASSWORD),
            full_name=DEMO_FULL_NAME,
        )
    )
    db.commit()


def _truck(
    unit_number: str,
    vehicle_class: VehicleClass,
    axle_count: int,
    home_terminal_city: str,
    *,
    has_trailer: bool = False,
    trailer_unit: str | None = None,
    trailer_size_class: TrailerSizeClass = TrailerSizeClass.NONE,
    has_liftgate: bool = False,
    has_dock_height: bool = True,
    heated: bool = False,
) -> Truck:
    weight, skids, feet, height = resolve_truck_capacity(
        vehicle_class.value,
        axle_count,
        has_trailer,
        trailer_size_class.value,
    )
    return Truck(
        unit_number=unit_number,
        vehicle_class=vehicle_class.value,
        axle_count=axle_count,
        max_weight_lbs=weight,
        max_skid_spots=skids,
        max_linear_feet=feet,
        max_interior_height_in=height,
        has_trailer=has_trailer,
        trailer_unit=trailer_unit,
        trailer_size_class=trailer_size_class.value,
        has_liftgate=has_liftgate,
        has_dock_height=has_dock_height,
        heated=heated,
        home_terminal_city=home_terminal_city,
        current_address=home_terminal_city,
        status=TruckStatus.AVAILABLE.value,
    )


def _pair_truck_ids(db: Session) -> dict[str, int]:
    """Map driver code → truck_id (prefer matching unit digits, else leftover 1:1)."""
    trucks = db.query(Truck).order_by(Truck.unit_number).all()
    by_digits: dict[str, Truck] = {}
    for t in trucks:
        digits = "".join(ch for ch in t.unit_number if ch.isdigit())
        if digits:
            by_digits[digits] = t
    used: set[int] = set()
    mapping: dict[str, int] = {}
    codes = ["113", "202", "227", "120", "205", "231"]
    leftover = list(trucks)
    for code in codes:
        truck = by_digits.get(code)
        if truck is not None and truck.id not in used:
            mapping[code] = truck.id
            used.add(truck.id)
            leftover = [t for t in leftover if t.id != truck.id]
    for code in codes:
        if code in mapping:
            continue
        if not leftover:
            break
        t = leftover.pop(0)
        mapping[code] = t.id
    return mapping


def seed_drivers(db: Session) -> None:
    if db.query(Driver).count() > 0:
        return
    if db.query(Truck).count() == 0:
        return
    pairs = _pair_truck_ids(db)
    depot_city = (_load_elite().get("depot") or {}).get("city") or "Scarborough"
    drivers = [
        Driver(
            code="113",
            name=_elite_driver_name("113", "Sivasubramaniam Thayaparan"),
            status=DriverStatus.AVAILABLE.value,
            licence_class=LicenceClass.AZ.value,
            can_dangerous_goods=True,
            can_heated=True,
            can_liftgate_runs=True,
            shift_start_min=6 * 60,
            shift_end_min=20 * 60,
            home_terminal_city=depot_city,
            truck_id=pairs["113"],
        ),
        Driver(
            code="202",
            name=_elite_driver_name("202", "Ilionick Fervius"),
            status=DriverStatus.AVAILABLE.value,
            licence_class=LicenceClass.DZ.value,
            can_dangerous_goods=False,
            can_heated=False,
            can_liftgate_runs=True,
            shift_start_min=6 * 60,
            shift_end_min=20 * 60,
            home_terminal_city=depot_city,
            truck_id=pairs["202"],
        ),
        Driver(
            code="227",
            name=_elite_driver_name("227", "Najibullah Raufi"),
            status=DriverStatus.AVAILABLE.value,
            licence_class=LicenceClass.AZ.value,
            can_dangerous_goods=True,
            can_heated=False,
            can_liftgate_runs=False,
            shift_start_min=6 * 60,
            shift_end_min=20 * 60,
            home_terminal_city=depot_city,
            truck_id=pairs["227"],
        ),
        Driver(
            code="120",
            name=_elite_driver_name("120", "Thambirasa Asokkumar"),
            status=DriverStatus.AVAILABLE.value,
            licence_class=LicenceClass.G.value,
            can_dangerous_goods=False,
            can_heated=False,
            can_liftgate_runs=True,
            shift_start_min=6 * 60,
            shift_end_min=20 * 60,
            max_duty_hours=10,
            home_terminal_city=depot_city,
            truck_id=pairs["120"],
        ),
        Driver(
            code="205",
            name=_elite_driver_name("205", "Tariq Karwa"),
            status=DriverStatus.AVAILABLE.value,
            licence_class=LicenceClass.DZ.value,
            can_dangerous_goods=False,
            can_heated=True,
            can_liftgate_runs=False,
            shift_start_min=6 * 60,
            shift_end_min=20 * 60,
            home_terminal_city=depot_city,
            truck_id=pairs["205"],
        ),
        Driver(
            code="231",
            name=_elite_driver_name("231", "Dimitrios Prepos"),
            status=DriverStatus.AVAILABLE.value,
            licence_class=LicenceClass.AZ.value,
            can_dangerous_goods=True,
            can_heated=True,
            can_liftgate_runs=True,
            shift_start_min=6 * 60,
            shift_end_min=20 * 60,
            home_terminal_city=depot_city,
            truck_id=pairs["231"],
        ),
    ]
    db.add_all(drivers)
    db.commit()


def seed_fleet_and_orders(db: Session) -> None:
    if db.query(Truck).count() > 0 or db.query(Order).count() > 0:
        return

    elite = _load_elite()
    depot = elite.get("depot") or {}
    depot_city = depot.get("city") or "Scarborough"
    depot_address = depot.get("address") or f"2215 Markham Rd, {depot_city}, ON"

    trucks = [
        _truck(
            "Truck #202",
            VehicleClass.TRUCK,
            3,
            depot_city,
            has_liftgate=True,
            has_dock_height=True,
        ),
        _truck(
            "Truck #213",
            VehicleClass.TRUCK,
            2,
            depot_city,
            has_liftgate=False,
            has_dock_height=True,
        ),
        _truck(
            "Truck #227",
            VehicleClass.TRACTOR,
            5,
            depot_city,
            has_trailer=True,
            trailer_unit="Trailer #530129",
            trailer_size_class=TrailerSizeClass.FT53,
            has_liftgate=False,
            has_dock_height=True,
        ),
        _truck(
            "Truck #231",
            VehicleClass.TRACTOR,
            5,
            depot_city,
            has_trailer=True,
            trailer_unit="Trailer #530935",
            trailer_size_class=TrailerSizeClass.FT53,
            has_liftgate=True,
            has_dock_height=True,
        ),
        _truck(
            "Truck #120",
            VehicleClass.VAN,
            2,
            depot_city,
            has_liftgate=True,
            has_dock_height=False,
        ),
        _truck(
            "Truck #205",
            VehicleClass.TRUCK,
            3,
            depot_city,
            has_liftgate=False,
            has_dock_height=True,
            heated=True,
        ),
    ]
    for t in trucks:
        t.current_address = depot_address
    db.add_all(trucks)
    db.flush()

    # Fallback street stubs if Elite address missing for an ordno
    _ADDR = {
        "Markham": "90 Royal Crest Ct",
        "Scarborough": "2215 Markham Rd",
        "Toronto": "401 Norfinch Dr",
        "Mississauga": "1600 Aimco Blvd",
        "Brampton": "9200 Airport Rd",
        "Pickering": "1550 Kingston Rd",
        "London": "300 Dufferin Ave",
        "Windsor": "650 Division Road",
        "Woodbridge": "7600 Weston Rd",
        "Vaughan": "865 Gibraltor Rd",
        "Concord": "200 Bradwick Dr",
        "Hamilton": "86 Main Street",
        "Milton": "150 Mary St",
        "Barrie": "70 Collier St",
        "Richmond Hill": "225 East Beaver Creek Rd",
        "Newmarket": "195 Harry Walker Pkwy N",
        "Guelph": "935 Southgate Drive",
        "Bolton": "12724 Coleraine Drive",
        "Burlington": "3315 Fairview St",
        "Kitchener": "4396 King Street",
        "Dundas": "86 Main Street",
    }

    def _pair(
        ordno: str,
        o_city: str,
        d_city: str,
        o_street: str | None = None,
        d_street: str | None = None,
    ):
        elite_a = _elite_addr(ordno)
        if elite_a:
            return {
                "origin_city": elite_a.get("origin_city") or o_city,
                "destination_city": elite_a.get("destination_city") or d_city,
                "origin_address": elite_a.get("origin_address")
                or f"{o_street or _ADDR.get(o_city, '1 Main St')}, {o_city}, ON",
                "destination_address": elite_a.get("destination_address")
                or f"{d_street or _ADDR.get(d_city, '1 Main St')}, {d_city}, ON",
            }
        o_st = o_street or _ADDR.get(o_city, "1 Main St")
        d_st = d_street or _ADDR.get(d_city, "1 Main St")
        return {
            "origin_city": o_city,
            "destination_city": d_city,
            "origin_address": f"{o_st}, {o_city}, ON",
            "destination_address": f"{d_st}, {d_city}, ON",
        }

    orders = [
        Order(
            ordno="2986297",
            reference="GTA-LTL-001",
            **_pair("2986297", "Markham", "Scarborough"),
            weight_lbs=850,
            skid_spots=2,
            linear_feet=4,
            dim_weight=900,
            pieces=2,
            stackable=True,
            height_in=48,
            service=OrderService.LTL.value,
            equipment_required=EquipmentRequired.TRUCK.value,
            requires_liftgate=False,
            status=OrderStatus.UNASSIGNED.value,
        ),
        Order(
            ordno="2986405",
            reference="GTA-RUSH-002",
            **_pair("2986405", "Scarborough", "Toronto"),
            weight_lbs=120,
            skid_spots=0,
            linear_feet=1,
            pieces=1,
            stackable=False,
            height_in=24,
            service=OrderService.RUSH.value,
            equipment_required=EquipmentRequired.ANY.value,
            requires_liftgate=True,
            residential=True,
            delivery_window_end=_day_dt(15, 0),
            status=OrderStatus.UNASSIGNED.value,
        ),
        Order(
            ordno="2987105",
            reference="GTA-OVN-003",
            **_pair("2987105", "Mississauga", "Brampton"),
            weight_lbs=3200,
            skid_spots=4,
            linear_feet=8,
            dim_weight=2800,
            pieces=8,
            stackable=False,
            height_in=60,
            service=OrderService.OVERNIGHT.value,
            equipment_required=EquipmentRequired.TRUCK.value,
            appointment=True,
            delivery_window_start=_day_dt(8, 0),
            delivery_window_end=_day_dt(11, 0),
            status=OrderStatus.UNASSIGNED.value,
        ),
        Order(
            ordno="2987417",
            reference="GTA-LTL-004",
            **_pair("2987417", "Scarborough", "Pickering"),
            weight_lbs=500,
            skid_spots=1,
            linear_feet=2,
            pieces=3,
            stackable=True,
            height_in=40,
            service=OrderService.LTL.value,
            equipment_required=EquipmentRequired.ANY.value,
            delivery_window_end=_day_dt(16, 0),
            status=OrderStatus.UNASSIGNED.value,
        ),
        Order(
            ordno="2987877",
            reference="GTA-OOT-005",
            **_pair("2987877", "Pickering", "London"),
            weight_lbs=12_500,
            skid_spots=10,
            linear_feet=20,
            pieces=15,
            stackable=False,
            height_in=72,
            service=OrderService.OUT_OF_TOWN.value,
            equipment_required=EquipmentRequired.TRAILER_53.value,
            status=OrderStatus.UNASSIGNED.value,
        ),
        Order(
            ordno="2988001",
            reference="GTA-FTL-006",
            **_pair("2988001", "Brampton", "Windsor"),
            weight_lbs=28_000,
            skid_spots=18,
            linear_feet=40,
            pieces=22,
            stackable=False,
            height_in=80,
            service=OrderService.FTL.value,
            equipment_required=EquipmentRequired.TRAILER_53.value,
            status=OrderStatus.UNASSIGNED.value,
        ),
        Order(
            ordno="2988102",
            reference="GTA-INS-007",
            **_pair("2988102", "Toronto", "Toronto", d_street="250 Yonge St"),
            weight_lbs=400,
            skid_spots=1,
            linear_feet=2,
            pieces=2,
            stackable=True,
            height_in=36,
            service=OrderService.SAME_DAY.value,
            equipment_required=EquipmentRequired.VAN.value,
            requires_liftgate=True,
            inside_delivery=True,
            status=OrderStatus.UNASSIGNED.value,
        ),
        Order(
            ordno="2988203",
            reference="GTA-LTL-008",
            **_pair("2988203", "Woodbridge", "Concord"),
            weight_lbs=2100,
            skid_spots=3,
            linear_feet=6,
            pieces=5,
            stackable=False,
            height_in=55,
            service=OrderService.LTL.value,
            equipment_required=EquipmentRequired.TRUCK.value,
            status=OrderStatus.UNASSIGNED.value,
        ),
        Order(
            ordno="2988304",
            reference="GTA-DG-009",
            **_pair("2988304", "Mississauga", "Hamilton"),
            weight_lbs=1800,
            skid_spots=2,
            linear_feet=5,
            pieces=4,
            stackable=False,
            height_in=50,
            service=OrderService.OVERNIGHT.value,
            equipment_required=EquipmentRequired.TRUCK.value,
            dangerous_goods=True,
            status=OrderStatus.UNASSIGNED.value,
        ),
        Order(
            ordno="2988405",
            reference="GTA-HEAT-010",
            **_pair("2988405", "Milton", "Barrie"),
            weight_lbs=900,
            skid_spots=2,
            linear_feet=3,
            pieces=2,
            stackable=True,
            height_in=42,
            service=OrderService.LTL.value,
            equipment_required=EquipmentRequired.ANY.value,
            heated=True,
            status=OrderStatus.UNASSIGNED.value,
        ),
        Order(
            ordno="2988506",
            reference="GTA-LTL-011",
            **_pair("2988506", "Richmond Hill", "Markham"),
            weight_lbs=650,
            skid_spots=1,
            linear_feet=2,
            pieces=2,
            stackable=True,
            height_in=44,
            service=OrderService.LTL.value,
            equipment_required=EquipmentRequired.TRUCK.value,
            status=OrderStatus.UNASSIGNED.value,
        ),
        Order(
            ordno="2988607",
            reference="GTA-HARD-012",
            **_pair("2988607", "Scarborough", "Newmarket"),
            weight_lbs=2200,
            skid_spots=3,
            linear_feet=6,
            pieces=4,
            stackable=False,
            height_in=70,
            service=OrderService.RUSH.value,
            equipment_required=EquipmentRequired.TRUCK.value,
            requires_liftgate=True,
            residential=True,
            status=OrderStatus.UNASSIGNED.value,
        ),
        # Intentionally hard: needs 53' length beyond straight-truck defaults
        Order(
            ordno="2988708",
            reference="GTA-OVER-013",
            **_pair("2988708", "Brampton", "Guelph"),
            weight_lbs=8_000,
            skid_spots=12,
            linear_feet=30,
            pieces=12,
            stackable=False,
            height_in=80,
            service=OrderService.LTL.value,
            equipment_required=EquipmentRequired.TRUCK.value,
            status=OrderStatus.UNASSIGNED.value,
        ),
        # Intentionally hard: liftgate + heated (no matching truck)
        Order(
            ordno="2988809",
            reference="GTA-HARD-014",
            **_pair("2988809", "Toronto", "Mississauga"),
            weight_lbs=700,
            skid_spots=1,
            linear_feet=2,
            pieces=1,
            stackable=False,
            height_in=48,
            service=OrderService.SAME_DAY.value,
            equipment_required=EquipmentRequired.ANY.value,
            requires_liftgate=True,
            heated=True,
            status=OrderStatus.UNASSIGNED.value,
        ),
        # Stackable companion (same footprint as 2987417) for stacking demos
        Order(
            ordno="2988911",
            reference="GTA-STACK-016",
            **_pair("2988911", "Scarborough", "Pickering"),
            weight_lbs=450,
            skid_spots=1,
            linear_feet=2,
            pieces=2,
            stackable=True,
            height_in=40,
            service=OrderService.LTL.value,
            equipment_required=EquipmentRequired.ANY.value,
            status=OrderStatus.UNASSIGNED.value,
        ),
        # Intentionally hard: appointment window already passed / impossible early
        Order(
            ordno="2988912",
            reference="GTA-APPT-017",
            **_pair("2988912", "Toronto", "Hamilton"),
            weight_lbs=900,
            skid_spots=2,
            linear_feet=4,
            pieces=2,
            stackable=False,
            height_in=48,
            service=OrderService.LTL.value,
            equipment_required=EquipmentRequired.TRUCK.value,
            appointment=True,
            delivery_window_start=_day_dt(6, 0),
            delivery_window_end=_day_dt(6, 30),
            status=OrderStatus.UNASSIGNED.value,
        ),
    ]
    db.add_all(orders)
    db.commit()


def seed_driver_truck_pairs(db: Session) -> None:
    """Ensure every driver has a unique truck_id (for DBs migrated from default_truck_id)."""
    trucks = db.query(Truck).order_by(Truck.unit_number).all()
    if not trucks:
        return
    by_code_suffix: dict[str, Truck] = {}
    for t in trucks:
        digits = "".join(ch for ch in t.unit_number if ch.isdigit())
        if digits:
            by_code_suffix[digits] = t

    used_truck_ids: set[int] = set()
    for d in db.query(Driver).filter(Driver.truck_id.isnot(None)).all():
        used_truck_ids.add(d.truck_id)

    unpaired = (
        db.query(Driver)
        .filter(Driver.truck_id.is_(None))
        .order_by(Driver.code)
        .all()
    )
    leftover_trucks = [t for t in trucks if t.id not in used_truck_ids]

    for d in unpaired:
        truck = by_code_suffix.get(d.code)
        if truck is not None and truck.id not in used_truck_ids:
            d.truck_id = truck.id
            used_truck_ids.add(truck.id)
            leftover_trucks = [t for t in leftover_trucks if t.id != truck.id]
            continue
        if leftover_trucks:
            truck = leftover_trucks.pop(0)
            d.truck_id = truck.id
            used_truck_ids.add(truck.id)

    db.commit()



def seed_all(db: Session) -> None:
    if os.environ.get("SEED_FORCE", "").strip() in {"1", "true", "True", "yes"}:
        clear_fleet_data(db)
    seed_demo_user(db)
    seed_fleet_and_orders(db)
    seed_drivers(db)
    seed_driver_truck_pairs(db)
