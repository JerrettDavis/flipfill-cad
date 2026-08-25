from __future__ import annotations

import numpy as np
import pytest

from flipfill.geometry.bounds import bounds_from_vertices, obb_from_vertices
from flipfill.geometry.primitives import make_primitive
from flipfill.geometry.tessellation import tessellate_shape
from flipfill.geometry.transforms import transform_matrix, transform_shape
from flipfill.model import PrimitiveKind, PrimitiveSpec, Transform, Vector3


def _box_corner_vertices(size: Vector3) -> np.ndarray:
    hx, hy, hz = size.x / 2.0, size.y / 2.0, size.z / 2.0
    corners = [
        (sx * hx, sy * hy, sz * hz)
        for sx in (-1, 1)
        for sy in (-1, 1)
        for sz in (-1, 1)
    ]
    return np.asarray(corners, dtype=float)


def _tessellated_world_vertices(size: Vector3, transform: Transform) -> np.ndarray:
    shape = transform_shape(
        make_primitive(PrimitiveSpec(PrimitiveKind.BOX, size)), transform
    )
    return tessellate_shape(shape, 0.05, 0.05).vertices


def test_obb_of_axis_aligned_box_matches_expected_dimensions() -> None:
    size = Vector3(20.0, 12.0, 6.0)
    vertices = _box_corner_vertices(size)

    obb = obb_from_vertices(vertices)

    assert sorted(obb.size.to_list()) == pytest.approx(sorted(size.to_list()), abs=1.0e-6)
    assert obb.center.to_list() == pytest.approx([0.0, 0.0, 0.0], abs=1.0e-6)
    assert obb.volume == pytest.approx(size.x * size.y * size.z, rel=1.0e-6)


def test_obb_needs_at_least_three_vertices() -> None:
    with pytest.raises(ValueError):
        obb_from_vertices(np.zeros((2, 3)))


@pytest.mark.parametrize("rotation_deg", [Vector3(0, 0, 37), Vector3(15, 25, 40)])
def test_obb_stays_tight_for_a_rotated_box(rotation_deg: Vector3) -> None:
    """The whole point of OBB: unlike an AABB, its volume should not
    inflate when the same box is rotated off the world axes."""

    size = Vector3(24.0, 16.0, 8.0)
    expected_volume = size.x * size.y * size.z
    vertices = _tessellated_world_vertices(size, Transform(rotation_deg=rotation_deg))

    obb = obb_from_vertices(vertices)
    aabb = bounds_from_vertices(vertices)

    assert obb.volume == pytest.approx(expected_volume, rel=0.01)
    assert aabb.volume > obb.volume * 1.05


def test_obb_orientation_reproduces_original_box() -> None:
    """The recovered rotation_deg must actually place every source vertex
    inside the recovered half-extents -- not just happen to match volume
    while pointing the box the wrong way."""

    size = Vector3(24.0, 16.0, 8.0)
    rotation_deg = Vector3(12.0, 22.0, 51.0)
    vertices = _tessellated_world_vertices(size, Transform(rotation_deg=rotation_deg))

    obb = obb_from_vertices(vertices)

    inverse = np.linalg.inv(
        transform_matrix(Transform(translation=obb.center, rotation_deg=obb.rotation_deg))
    )
    homogenous = np.column_stack((vertices, np.ones(len(vertices))))
    local = (inverse @ homogenous.T).T[:, :3]
    half_extents = np.asarray(obb.half_extents.to_list())

    assert np.all(np.abs(local) <= half_extents + 1.0e-3)
    assert obb.volume == pytest.approx(size.x * size.y * size.z, rel=0.01)
