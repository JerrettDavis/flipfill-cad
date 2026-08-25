from __future__ import annotations

import pytest

from flipfill.geometry.bounds import bounds_from_shape
from flipfill.geometry.primitives import PrimitiveError, make_primitive
from flipfill.model import PrimitiveKind, PrimitiveSpec, Vector3


@pytest.mark.parametrize(
    "kind",
    [
        PrimitiveKind.BOX,
        PrimitiveKind.ROUNDED_BOX,
        PrimitiveKind.CYLINDER,
        PrimitiveKind.SLOT,
    ],
)
def test_all_primitives_are_valid(kind: PrimitiveKind) -> None:
    shape = make_primitive(PrimitiveSpec(kind, Vector3(20, 12, 8), radius=2))
    assert shape.isValid()
    assert shape.Volume() > 0


def test_rounded_box_preserves_requested_bounds() -> None:
    shape = make_primitive(
        PrimitiveSpec(PrimitiveKind.ROUNDED_BOX, Vector3(30, 20, 10), radius=4)
    )
    bounds = bounds_from_shape(shape)
    assert bounds.size.x == pytest.approx(30)
    assert bounds.size.y == pytest.approx(20)
    assert bounds.size.z == pytest.approx(10)


def test_negative_size_rejected() -> None:
    with pytest.raises(PrimitiveError):
        make_primitive(PrimitiveSpec(PrimitiveKind.BOX, Vector3(-1, 2, 3)))
