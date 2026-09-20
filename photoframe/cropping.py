"""Coordinate validation shared by face metadata and the image renderer."""

import math


def finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def same_aspect_ratio(width: float, height: float, reference_width: float, reference_height: float) -> bool:
    # Allow two pixels of preview resize rounding, capped at 1%. Larger
    # differences suggest a different crop/orientation, not just a resize.
    tolerance = min(0.01, 2.0 / min(reference_width, reference_height))
    difference = math.log(width) - math.log(height) - math.log(reference_width) + math.log(reference_height)
    return abs(difference) <= tolerance
