"""HERE flexible-polyline decoder (lat/lng). Based on heremaps/flexible-polyline (MIT)."""

from __future__ import annotations

from app.services.geocode import LatLng

_DECODING_TABLE = [
    62,
    -1,
    -1,
    52,
    53,
    54,
    55,
    56,
    57,
    58,
    59,
    60,
    61,
    -1,
    -1,
    -1,
    -1,
    -1,
    -1,
    -1,
    0,
    1,
    2,
    3,
    4,
    5,
    6,
    7,
    8,
    9,
    10,
    11,
    12,
    13,
    14,
    15,
    16,
    17,
    18,
    19,
    20,
    21,
    22,
    23,
    24,
    25,
    -1,
    -1,
    -1,
    -1,
    63,
    -1,
    26,
    27,
    28,
    29,
    30,
    31,
    32,
    33,
    34,
    35,
    36,
    37,
    38,
    39,
    40,
    41,
    42,
    43,
    44,
    45,
    46,
    47,
    48,
    49,
    50,
    51,
]

_FORMAT_VERSION = 1


def _decode_char(char: str) -> int:
    char_value = ord(char)
    try:
        value = _DECODING_TABLE[char_value - 45]
    except IndexError as exc:
        raise ValueError("Invalid encoding") from exc
    if value < 0:
        raise ValueError("Invalid encoding")
    return value


def _to_signed(value: int) -> int:
    if value & 1:
        value = ~value
    value >>= 1
    return value


def _decode_unsigned_values(encoded: str):
    result = shift = 0
    for char in encoded:
        value = _decode_char(char)
        result |= (value & 0x1F) << shift
        if (value & 0x20) == 0:
            yield result
            result = shift = 0
        else:
            shift += 5
    if shift > 0:
        raise ValueError("Invalid encoding")


def decode_flexpolyline(encoded: str) -> list[LatLng]:
    """Decode a flexible polyline string into lat/lng points."""
    if not encoded:
        return []
    decoder = _decode_unsigned_values(encoded)
    version = next(decoder)
    if version != _FORMAT_VERSION:
        raise ValueError("Invalid format version")
    value = next(decoder)
    precision = value & 15
    value >>= 4
    third_dim = value & 7
    factor = 10.0**precision

    last_lat = last_lng = 0
    points: list[LatLng] = []
    while True:
        try:
            last_lat += _to_signed(next(decoder))
        except StopIteration:
            break
        try:
            last_lng += _to_signed(next(decoder))
            if third_dim:
                next(decoder)  # discard third dimension
            points.append(LatLng(lat=last_lat / factor, lng=last_lng / factor))
        except StopIteration as exc:
            raise ValueError("Invalid encoding. Premature ending reached") from exc
    return points
