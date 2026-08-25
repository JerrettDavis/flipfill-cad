from __future__ import annotations

from dataclasses import dataclass

import cadquery as cq
import numpy as np


@dataclass(slots=True)
class TriangleMesh:
    vertices: np.ndarray
    faces: np.ndarray


def tessellate_shape(
    shape: cq.Shape,
    linear_tolerance: float = 0.15,
    angular_tolerance: float = 0.1,
) -> TriangleMesh:
    vertices, triangles = shape.tessellate(linear_tolerance, angular_tolerance)
    vertex_array = np.asarray([[v.x, v.y, v.z] for v in vertices], dtype=float)
    face_array = np.asarray(triangles, dtype=np.int64)
    return TriangleMesh(vertex_array, face_array)
