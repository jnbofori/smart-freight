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
DEPOT_READY_MIN = 6 * 60  # 06:00


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
    if vehicle_class == VehicleClass.VAN.value:
        return 90
    if has_trailer or trailer_size_class == TrailerSizeClass.FT53.value:
        return 110
    if vehicle_class == VehicleClass.TRACTOR.value:
        return 90
    return 110
