from app.enums import (
    TrailerSizeClass,
    default_interior_height_in,
    default_max_weight_lbs,
    default_skid_and_feet,
)


def resolve_truck_capacity(
    vehicle_class: str,
    axle_count: int,
    has_trailer: bool,
    trailer_size_class: str,
    max_weight_lbs: int | None = None,
    max_skid_spots: int | None = None,
    max_linear_feet: int | None = None,
    max_interior_height_in: int | None = None,
) -> tuple[int, int, int, int]:
    """Return (max_weight_lbs, max_skid_spots, max_linear_feet, max_interior_height_in)."""
    size_class = trailer_size_class or TrailerSizeClass.NONE.value
    weight = max_weight_lbs if max_weight_lbs is not None else default_max_weight_lbs(
        vehicle_class, axle_count
    )
    default_skids, default_feet = default_skid_and_feet(vehicle_class, has_trailer, size_class)
    skids = max_skid_spots if max_skid_spots is not None else default_skids
    feet = max_linear_feet if max_linear_feet is not None else default_feet
    height = (
        max_interior_height_in
        if max_interior_height_in is not None
        else default_interior_height_in(vehicle_class, has_trailer, size_class)
    )
    return weight, skids, feet, height
