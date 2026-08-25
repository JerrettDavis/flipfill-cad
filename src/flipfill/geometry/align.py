from __future__ import annotations

from flipfill.geometry.bounds import Bounds3D

_AXIS_INDEX = {"x": 0, "y": 1, "z": 2}


class AlignError(ValueError):
    pass


def axis_index(axis: str) -> int:
    try:
        return _AXIS_INDEX[axis]
    except KeyError as exc:
        raise AlignError(f"Unknown axis '{axis}'; expected one of x, y, z") from exc


def bound_value(bounds: Bounds3D, axis: str, mode: str) -> float:
    """Return the requested edge/center coordinate of ``bounds`` along ``axis``.

    ``mode`` is one of ``min``, ``center``, or ``max`` and refers to the low
    face, midpoint, or high face of the bounding box on that axis.
    """

    index = axis_index(axis)
    if mode == "min":
        return bounds.minimum.to_list()[index]
    if mode == "center":
        return bounds.center.to_list()[index]
    if mode == "max":
        return bounds.maximum.to_list()[index]
    raise AlignError(f"Unknown alignment mode '{mode}'; expected one of min, center, max")
