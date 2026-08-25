from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import cadquery as cq
import numpy as np

from flipfill.model import Vector3


@dataclass(frozen=True, slots=True)
class Bounds3D:
    minimum: Vector3
    maximum: Vector3

    @property
    def center(self) -> Vector3:
        return Vector3(
            (self.minimum.x + self.maximum.x) / 2.0,
            (self.minimum.y + self.maximum.y) / 2.0,
            (self.minimum.z + self.maximum.z) / 2.0,
        )

    @property
    def size(self) -> Vector3:
        return Vector3(
            self.maximum.x - self.minimum.x,
            self.maximum.y - self.minimum.y,
            self.maximum.z - self.minimum.z,
        )

    @property
    def volume(self) -> float:
        size = self.size
        return max(0.0, size.x) * max(0.0, size.y) * max(0.0, size.z)

    def expanded(self, amount: Vector3 | float) -> Bounds3D:
        if isinstance(amount, (int, float)):
            amount = Vector3(float(amount), float(amount), float(amount))
        return Bounds3D(
            Vector3(
                self.minimum.x - amount.x,
                self.minimum.y - amount.y,
                self.minimum.z - amount.z,
            ),
            Vector3(
                self.maximum.x + amount.x,
                self.maximum.y + amount.y,
                self.maximum.z + amount.z,
            ),
        )

    def contains(self, other: Bounds3D, tolerance: float = 1.0e-6) -> bool:
        return (
            self.minimum.x <= other.minimum.x + tolerance
            and self.minimum.y <= other.minimum.y + tolerance
            and self.minimum.z <= other.minimum.z + tolerance
            and self.maximum.x + tolerance >= other.maximum.x
            and self.maximum.y + tolerance >= other.maximum.y
            and self.maximum.z + tolerance >= other.maximum.z
        )

    @classmethod
    def union(cls, bounds: Iterable[Bounds3D]) -> Bounds3D:
        values = list(bounds)
        if not values:
            raise ValueError("Cannot compute the union of an empty bounds collection")
        return cls(
            Vector3(
                min(v.minimum.x for v in values),
                min(v.minimum.y for v in values),
                min(v.minimum.z for v in values),
            ),
            Vector3(
                max(v.maximum.x for v in values),
                max(v.maximum.y for v in values),
                max(v.maximum.z for v in values),
            ),
        )


def bounds_from_shape(shape: cq.Shape) -> Bounds3D:
    box = shape.BoundingBox()
    return Bounds3D(
        Vector3(float(box.xmin), float(box.ymin), float(box.zmin)),
        Vector3(float(box.xmax), float(box.ymax), float(box.zmax)),
    )


def bounds_from_vertices(vertices: np.ndarray) -> Bounds3D:
    if vertices.size == 0:
        raise ValueError("Mesh has no vertices")
    low = np.min(vertices, axis=0)
    high = np.max(vertices, axis=0)
    return Bounds3D(
        Vector3(float(low[0]), float(low[1]), float(low[2])),
        Vector3(float(high[0]), float(high[1]), float(high[2])),
    )
