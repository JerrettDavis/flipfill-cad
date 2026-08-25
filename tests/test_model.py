from __future__ import annotations

from flipfill.model import (
    ClearanceMode,
    ObjectRole,
    PrimitiveKind,
    PrimitiveSpec,
    Project,
    SceneObject,
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
