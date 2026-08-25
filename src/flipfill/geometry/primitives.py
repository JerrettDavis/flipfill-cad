from __future__ import annotations

import cadquery as cq

from flipfill.geometry.transforms import transform_shape
from flipfill.model import PrimitiveKind, PrimitiveSpec, Transform, Vector3


class PrimitiveError(ValueError):
    pass


def _validate_size(size: Vector3) -> None:
    if size.x <= 0 or size.y <= 0 or size.z <= 0:
        raise PrimitiveError(
            f"Primitive dimensions must be positive; received {size.to_list()}"
        )


def make_primitive(spec: PrimitiveSpec, transform: Transform | None = None) -> cq.Shape:
    _validate_size(spec.size)
    size = spec.size

    if spec.kind is PrimitiveKind.BOX:
        shape = cq.Workplane("XY").box(size.x, size.y, size.z, centered=True).val()
    elif spec.kind is PrimitiveKind.ROUNDED_BOX:
        maximum_radius = max(0.0, min(size.x, size.y) / 2.0 - 1.0e-3)
        radius = max(0.0, min(float(spec.radius), maximum_radius))
        workplane = cq.Workplane("XY").box(size.x, size.y, size.z, centered=True)
        if radius > 1.0e-6:
            workplane = workplane.edges("|Z").fillet(radius)
        shape = workplane.val()
    elif spec.kind is PrimitiveKind.CYLINDER:
        # size.x is the diameter; size.z is the height. size.y is retained for
        # serialization/UI consistency but is not used by the cylinder kernel.
        shape = (
            cq.Workplane("XY")
            .cylinder(size.z, size.x / 2.0, centered=True)
            .val()
        )
    elif spec.kind is PrimitiveKind.SLOT:
        diameter = min(size.x, size.y)
        centerline_length = max(0.0, max(size.x, size.y) - diameter)
        slot_length = centerline_length + diameter
        angle = 0.0 if size.x >= size.y else 90.0
        shape = (
            cq.Workplane("XY")
            .slot2D(slot_length, diameter, angle=angle)
            .extrude(size.z / 2.0, both=True)
            .val()
        )
    else:  # pragma: no cover - Enum makes this defensive branch unreachable
        raise PrimitiveError(f"Unsupported primitive kind: {spec.kind}")

    return transform_shape(shape, transform) if transform is not None else shape


def make_aabb(size: Vector3, center: Vector3) -> cq.Shape:
    return make_primitive(
        PrimitiveSpec(kind=PrimitiveKind.BOX, size=size),
        Transform(translation=center),
    )
