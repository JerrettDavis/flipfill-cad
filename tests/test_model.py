from __future__ import annotations

from flipfill.model import (
    ClearanceMode,
    ObjectRole,
    PrimitiveKind,
    PrimitiveSpec,
    Project,
    SceneObject,
    SliceCutterKind,
    SliceSpec,
    Transform,
    Vector3,
)


def test_project_round_trip() -> None:
    project = Project(name="Round trip")
    project.objects.append(
        SceneObject(
            name="Battery",
            role=ObjectRole.OCCUPANT,
            primitive=PrimitiveSpec(
                PrimitiveKind.ROUNDED_BOX, Vector3(100, 60, 11), 2
            ),
            transform=Transform(Vector3(1, 2, 3), Vector3(0, 90, 0)),
            clearance_mode=ClearanceMode.AABB,
            clearance_mm=0.75,
        )
    )

    restored = Project.from_dict(project.to_dict())

    assert restored.to_dict() == project.to_dict()
    assert restored.objects[0].geometry_kind.value == "primitive"


def test_vector_parsing() -> None:
    assert Vector3.from_value([1, 2, 3]) == Vector3(1, 2, 3)
    assert Vector3.from_value({"x": 4, "y": 5, "z": 6}) == Vector3(4, 5, 6)


def test_slicing_round_trip() -> None:
    project = Project(name="Slicing round trip")
    project.slicing.enabled = True
    project.slicing.remainder_name = "Rear Shell"
    project.slicing.slices.append(
        SliceSpec(
            name="Front Bezel",
            cutter_kind=SliceCutterKind.PLANE,
            transform=Transform(Vector3(0, 0, 8), Vector3(0, 0, 0)),
            gap=0.3,
        )
    )
    project.slicing.slices.append(
        SliceSpec(
            name="Battery Pocket",
            cutter_kind=SliceCutterKind.OBJECT,
            object_id="some-object-id",
        )
    )

    restored = Project.from_dict(project.to_dict())

    assert restored.to_dict() == project.to_dict()
    assert restored.slicing.enabled is True
    assert restored.slicing.remainder_name == "Rear Shell"
    assert restored.slicing.slices[0].cutter_kind is SliceCutterKind.PLANE
    assert restored.slicing.slices[0].transform.translation == Vector3(0, 0, 8)
    assert restored.slicing.slices[0].gap == 0.3
    assert restored.slicing.slices[1].cutter_kind is SliceCutterKind.OBJECT
    assert restored.slicing.slices[1].object_id == "some-object-id"


def test_slicing_defaults_to_disabled_with_no_slices() -> None:
    project = Project()
    assert project.slicing.enabled is False
    assert project.slicing.slices == []
    assert project.slicing.remainder_name == "Remainder"
