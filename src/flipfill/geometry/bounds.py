from __future__ import annotations

import math
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


@dataclass(frozen=True, slots=True)
class OrientedBounds:
    """A world-space oriented bounding box: a rotated box, not axis-aligned.

    ``rotation_deg`` uses the same X-then-Y-then-Z degree convention as
    :class:`flipfill.model.Transform` (see
    ``flipfill.geometry.transforms.transform_matrix``), so it can be applied
    directly as a ``Transform`` to position a box primitive on these axes.
    """

    center: Vector3
    half_extents: Vector3
    rotation_deg: Vector3

    @property
    def size(self) -> Vector3:
        return Vector3(
            self.half_extents.x * 2.0, self.half_extents.y * 2.0, self.half_extents.z * 2.0
        )

    @property
    def volume(self) -> float:
        size = self.size
        return max(0.0, size.x) * max(0.0, size.y) * max(0.0, size.z)

    def expanded(self, amount: float) -> OrientedBounds:
        amount = max(0.0, amount)
        return OrientedBounds(
            center=self.center,
            half_extents=Vector3(
                self.half_extents.x + amount,
                self.half_extents.y + amount,
                self.half_extents.z + amount,
            ),
            rotation_deg=self.rotation_deg,
        )


def _axes_to_xyz_degrees(axes: np.ndarray) -> Vector3:
    """Recover X/Y/Z degrees for the rotation matrix ``axes`` (columns are
    the local X/Y/Z axes in world space), matching the X-then-Y-then-Z
    convention (``R = Rz(rz) @ Ry(ry) @ Rx(rx)``) that
    ``flipfill.geometry.transforms.transform_matrix`` produces from
    ``Transform.rotation_deg``. Falls back to a valid (if not unique)
    decomposition at the gimbal-lock singularity (``ry`` = +-90 degrees).
    """

    sin_ry = float(np.clip(axes[2, 0], -1.0, 1.0))
    ry = -math.asin(sin_ry)
    cos_ry = math.cos(ry)
    if abs(cos_ry) > 1.0e-6:
        rx = math.atan2(axes[2, 1], axes[2, 2])
        rz = math.atan2(axes[1, 0], axes[0, 0])
    else:
        rx = 0.0
        rz = math.atan2(-axes[0, 1], axes[1, 1])
    return Vector3(math.degrees(rx), math.degrees(ry), math.degrees(rz))


def obb_from_vertices(vertices: np.ndarray) -> OrientedBounds:
    """Compute a world-space oriented bounding box from a point cloud.

    Uses PCA on the vertex covariance to pick box axes: for real hardware
    geometry (not a perfect sphere/cube) this tracks the part's dominant
    directions closely and gives a much tighter conservative volume than an
    axis-aligned box for anything rotated off the world axes. It is not
    guaranteed to be the minimum-volume oriented box (that requires a
    convex-hull rotating-calipers search), but is deterministic, cheap, and
    a strict improvement over AABB for clearance purposes.
    """

    if vertices.shape[0] < 3:
        raise ValueError("Need at least 3 vertices to compute an oriented bounding box")

    mean = vertices.mean(axis=0)
    centered = vertices - mean
    covariance = np.cov(centered, rowvar=False)
    # Eigenvectors of a real symmetric matrix are orthonormal; eigh returns
    # them ascending by eigenvalue, so reverse for largest-variance-first.
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    order = np.argsort(eigenvalues)[::-1]
    axes = eigenvectors[:, order]
    if np.linalg.det(axes) < 0.0:
        # eigh can hand back a reflection; flip one axis to keep a proper
        # (determinant +1) rotation, which is what Transform.rotation_deg
        # can actually represent.
        axes[:, 2] *= -1.0

    local = centered @ axes
    local_min = local.min(axis=0)
    local_max = local.max(axis=0)
    local_center = (local_min + local_max) / 2.0
    half_extents = (local_max - local_min) / 2.0
    world_center = mean + axes @ local_center

    return OrientedBounds(
        center=Vector3(float(world_center[0]), float(world_center[1]), float(world_center[2])),
        half_extents=Vector3(
            float(half_extents[0]), float(half_extents[1]), float(half_extents[2])
        ),
        rotation_deg=_axes_to_xyz_degrees(axes),
    )
