from __future__ import annotations

import cadquery as cq
from OCP.BRepOffset import BRepOffset_Skin
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeOffsetShape
from OCP.GeomAbs import GeomAbs_Arc


class OffsetError(RuntimeError):
    pass


def offset_shape(shape: cq.Shape, distance: float, tolerance: float = 1.0e-4) -> cq.Shape:
    """Create an outward BRep offset, processing compounds solid-by-solid.

    OpenCascade's 3D offset is powerful but can fail on non-manifold, C0, or very
    detailed imported geometry. Callers should expose an AABB fallback rather than
    silently trusting an invalid offset.
    """

    if distance <= 0:
        return shape

    solids = shape.Solids()
    targets = solids if solids else [shape]
    outputs: list[cq.Shape] = []

    for target in targets:
        maker = BRepOffsetAPI_MakeOffsetShape()
        try:
            maker.PerformByJoin(
                target.wrapped,
                float(distance),
                float(tolerance),
                BRepOffset_Skin,
                False,
                False,
                GeomAbs_Arc,
                True,
            )
        except Exception as exc:  # pragma: no cover - OCCT exception text varies
            raise OffsetError(f"OpenCascade offset failed: {exc}") from exc
        if not maker.IsDone():
            raise OffsetError("OpenCascade did not complete the offset operation")
        result = cq.Shape(maker.Shape())
        if result.isNull() or not result.isValid():
            raise OffsetError("Offset result is null or invalid")
        outputs.append(result)

    combined = outputs[0]
    for output in outputs[1:]:
        combined = combined.fuse(output, tol=tolerance)
    return combined.clean()
