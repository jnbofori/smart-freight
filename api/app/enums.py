import enum


class VehicleClass(str, enum.Enum):
    TRUCK = "truck"
    TRACTOR = "tractor"
    VAN = "van"


class TrailerSizeClass(str, enum.Enum):
    FT53 = "ft53"
    NONE = "none"


class TruckStatus(str, enum.Enum):
    AVAILABLE = "available"
    ASSIGNED = "assigned"
    OUT_OF_SERVICE = "out_of_service"


class EquipmentRequired(str, enum.Enum):
    TRUCK = "truck"
    TRAILER_53 = "trailer_53"
    TRACTOR = "tractor"
    VAN = "van"
    ANY = "any"


class OrderService(str, enum.Enum):
    LTL = "LTL"
    OVERNIGHT = "OVERNIGHT"
    RUSH = "RUSH"
    SAME_DAY = "SAME DAY"
    OUT_OF_TOWN = "OUT OF TOWN"
    AFTER_HOURS = "AFTER HOURS"
    FLAT_BED = "FLAT BED"
    FTL = "FTL"
    EXPEDITE = "EXPEDITE"
    OTHER = "OTHER"


class OrderStatus(str, enum.Enum):
    UNASSIGNED = "unassigned"
    ASSIGNED = "assigned"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class DriverStatus(str, enum.Enum):
    AVAILABLE = "available"
    ASSIGNED = "assigned"
    OFF = "off"
    OUT_OF_SERVICE = "out_of_service"


class LicenceClass(str, enum.Enum):
    G = "G"
    DZ = "DZ"
    AZ = "AZ"


SERVICE_TIME_MIN = 15
DEFAULT_TRAVEL_MIN = 45
# Operational morning start
DEPOT_READY_MIN = 6 * 60  # 06:00
PRE_TRIP_INSPECTION_MIN = 15
# Mid-shift demo clock for dispatch / breakdown / cancel rebuilds
MID_SHIFT_CLOCK_MIN = 12 * 60  # 12:00


class HosDutyStatus(str, enum.Enum):
    OFF_DUTY = "off_duty"
    SLEEPER = "sleeper"
    DRIVING = "driving"
    ON_DUTY_NOT_DRIVING = "on_duty_not_driving"


class HosCycle(str, enum.Enum):
    CYCLE_70_7 = "cycle_70_7"
    CYCLE_120_14 = "cycle_120_14"


# O. Reg. 555/06–inspired hard caps (prototype; not legal advice)
HOS_MAX_DRIVE_MIN = 13 * 60
HOS_MAX_ON_DUTY_MIN = 14 * 60
HOS_MAX_ELAPSED_MIN = 16 * 60
HOS_MIN_OFF_DUTY_DAY_MIN = 10 * 60
HOS_QUALIFYING_REST_MIN = 8 * 60
HOS_CYCLE_70_7_MIN = 70 * 60
HOS_CYCLE_120_14_MIN = 120 * 60
HOS_CYCLE_120_RESET_24_MIN = 24 * 60
HOS_CYCLE_120_RESET_72_MIN = 72 * 60


# Prototype axle → max weight (lb). Not full CVOR law — documented assumptions.
AXLE_WEIGHT_LBS: dict[tuple[str, int], int] = {
    (VehicleClass.VAN.value, 2): 10_000,
    (VehicleClass.TRUCK.value, 2): 26_000,
    (VehicleClass.TRUCK.value, 3): 33_000,
    (VehicleClass.TRACTOR.value, 3): 45_000,
    (VehicleClass.TRACTOR.value, 4): 60_000,
    (VehicleClass.TRACTOR.value, 5): 80_000,
    (VehicleClass.TRACTOR.value, 6): 80_000,
}


def default_max_weight_lbs(vehicle_class: str, axle_count: int) -> int:
    key = (vehicle_class, axle_count)
    if key in AXLE_WEIGHT_LBS:
        return AXLE_WEIGHT_LBS[key]
    # Fallback: interpolate by nearest axle count for class
    candidates = [(axles, w) for (vc, axles), w in AXLE_WEIGHT_LBS.items() if vc == vehicle_class]
    if not candidates:
        return 26_000
    candidates.sort(key=lambda pair: abs(pair[0] - axle_count))
    return candidates[0][1]


def default_skid_and_feet(
    vehicle_class: str,
    has_trailer: bool,
    trailer_size_class: str,
) -> tuple[int, int]:
    """Return (max_skid_spots, max_linear_feet)."""
    if has_trailer or trailer_size_class == TrailerSizeClass.FT53.value:
        return 26, 53
    if vehicle_class == VehicleClass.VAN.value:
        return 4, 12
    if vehicle_class == VehicleClass.TRACTOR.value:
        # Tractor without trailer — minimal cargo box assumption
        return 2, 8
    # Straight truck
    return 10, 24


# Prototype interior clear heights (inches). Not OEM specs.
MAX_STACK_LAYERS = 2


def default_interior_height_in(
    vehicle_class: str,
    has_trailer: bool,
    trailer_size_class: str,
) -> int:
    """Prototype interior clear heights (inches).

    Trailers ~108 in; straight trucks ~84 in; cargo vans ~81 in
    (typical high-roof work van, e.g. Ford Transit high roof ~81.5 in;
    Sprinter/ProMaster high roofs are ~76–81 in).
    """
    if has_trailer or trailer_size_class == TrailerSizeClass.FT53.value:
        return 108
    if vehicle_class == VehicleClass.VAN.value:
        return 81
    return 84
