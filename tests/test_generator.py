from __future__ import annotations

import pytest

from flipfill.geometry.generator import fit_envelope_to_objects, generate
from flipfill.geometry.importers import GeometryRepository
from flipfill.model import (
    ClearanceMode,
    ObjectRole,
    PrimitiveKind,
    PrimitiveSpec,
    Project,
    SceneObject,
    SplitAxis,
    Transform,
    Vector3,
)


def box_object(
    name: str,
    size: Vector3,
    role: ObjectRole,
    center: Vector3 | None = None,
    clearance: float = 0.0,
    mode: ClearanceMode = ClearanceMode.EXACT,
) -> SceneObject:
    return SceneObject(
        name=name,
        role=role,
        primitive=PrimitiveSpec(PrimitiveKind.BOX, size),
        transform=Transform(translation=center if center is not None else Vector3()),
        clearance_mode=mode,
        clearance_mm=clearance,
        included_in_envelope_fit=role is not ObjectRole.CUTOUT,
    )


def test_inverse_fill_volume() -> None:
    project = Project()
    project.envelope.kind = PrimitiveKind.BOX
    project.envelope.size = Vector3(20, 20, 20)
    project.objects.append(
        box_object("cavity", Vector3(10, 10, 10), ObjectRole.OCCUPANT)
    )

    result = generate(project)

    assert result.result.Volume() == pytest.approx(20**3 - 10**3, abs=1.0e-6)
    assert not result.errors


def test_aabb_clearance_is_subtracted() -> None:
    project = Project()
    project.envelope.kind = PrimitiveKind.BOX
    project.envelope.size = Vector3(30, 30, 30)
    project.objects.append(
        box_object(
            "cavity",
            Vector3(10, 10, 10),
            ObjectRole.OCCUPANT,
            clearance=1,
            mode=ClearanceMode.AABB,
        )
    )

    result = generate(project)

    assert result.result.Volume() == pytest.approx(30**3 - 12**3, abs=1.0e-5)


def test_exact_offset_clearance() -> None:
    project = Project()
    project.envelope.kind = PrimitiveKind.BOX
    project.envelope.size = Vector3(30, 30, 30)
    project.objects.append(
        box_object(
            "cavity",
            Vector3(10, 10, 10),
            ObjectRole.OCCUPANT,
            clearance=1,
            mode=ClearanceMode.OFFSET,
        )
    )

    result = generate(project)

    assert result.result.Volume() < 30**3 - 10**3
    assert not result.errors


def test_cutout_opens_outer_wall() -> None:
    project = Project()
    project.envelope.kind = PrimitiveKind.BOX
    project.envelope.size = Vector3(20, 20, 20)
    project.objects.append(
        box_object(
            "port",
            Vector3(10, 4, 4),
            ObjectRole.CUTOUT,
            center=Vector3(8, 0, 0),
        )
    )

    result = generate(project)

    assert result.result.Volume() == pytest.approx(20**3 - 7 * 4 * 4, abs=1.0e-5)
    assert not result.errors


def test_additive_is_fused() -> None:
    project = Project()
    project.envelope.kind = PrimitiveKind.BOX
    project.envelope.size = Vector3(10, 10, 10)
    project.objects.append(
        box_object(
            "boss",
            Vector3(4, 4, 4),
            ObjectRole.ADDITIVE,
            center=Vector3(0, 0, 6),
        )
    )

    result = generate(project)

    assert result.result.Volume() == pytest.approx(10**3 + 4 * 4 * 3, abs=1.0e-5)


def test_fit_envelope_applies_margin() -> None:
    project = Project()
    project.envelope.fit_margin = Vector3(2, 3, 4)
    project.envelope.transform.rotation_deg = Vector3(0, 0, 30)
    project.objects.extend(
        [
            box_object("left", Vector3(10, 10, 10), ObjectRole.OCCUPANT, Vector3(-10, 0, 0)),
            box_object("right", Vector3(6, 8, 12), ObjectRole.OCCUPANT, Vector3(12, 1, 2)),
        ]
    )

    fitted = fit_envelope_to_objects(project, GeometryRepository())

    assert project.envelope.size == fitted.size
    assert fitted.size.x == pytest.approx(34)
    assert fitted.size.y == pytest.approx(16)
    assert fitted.size.z == pytest.approx(21)
    assert project.envelope.transform.rotation_deg == Vector3()


def test_split_produces_two_valid_halves() -> None:
    project = Project()
    project.envelope.kind = PrimitiveKind.BOX
    project.envelope.size = Vector3(20, 20, 20)
    project.split.enabled = True
    project.split.axis = SplitAxis.Z
    project.split.offset = 0
    project.split.gap = 0.4

    result = generate(project)

    assert result.split_a is not None
    assert result.split_b is not None
    assert result.split_a.isValid()
    assert result.split_b.isValid()
    assert result.split_a.Volume() + result.split_b.Volume() == pytest.approx(
        20 * 20 * 19.6, abs=1.0e-5
    )


def test_overlapping_occupants_warn() -> None:
    project = Project()
    project.envelope.kind = PrimitiveKind.BOX
    project.envelope.size = Vector3(30, 30, 30)
    project.objects.extend(
        [
            box_object("one", Vector3(10, 10, 10), ObjectRole.OCCUPANT),
            box_object(
                "two", Vector3(10, 10, 10), ObjectRole.OCCUPANT, Vector3(5, 0, 0)
            ),
        ]
    )

    result = generate(project)

    assert any("overlaps" in message.message for message in result.warnings)
