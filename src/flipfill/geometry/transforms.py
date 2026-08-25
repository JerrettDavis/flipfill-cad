from __future__ import annotations

import cadquery as cq
import numpy as np

from flipfill.model import Transform


def cadquery_location(transform: Transform) -> cq.Location:
    t = transform.translation
    r = transform.rotation_deg
    return cq.Location(t.x, t.y, t.z, r.x, r.y, r.z)


def transform_shape(shape: cq.Shape, transform: Transform) -> cq.Shape:
    return shape.located(cadquery_location(transform))


def transform_matrix(transform: Transform) -> np.ndarray:
    """Return the same 4x4 transform matrix OpenCascade uses for cq.Location."""

    trsf = cadquery_location(transform).wrapped.Transformation()
    matrix = np.eye(4, dtype=float)
    for row in range(1, 4):
        for column in range(1, 5):
            matrix[row - 1, column - 1] = trsf.Value(row, column)
    return matrix


def transform_vertices(vertices: np.ndarray, transform: Transform) -> np.ndarray:
    if vertices.size == 0:
        return vertices.copy()
    homogenous = np.column_stack((vertices, np.ones(len(vertices), dtype=float)))
    return (transform_matrix(transform) @ homogenous.T).T[:, :3]
