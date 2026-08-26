"""BDD scenario for the slice/cut tool, driven through flipfill.commands
exactly like tests/test_e2e.py drives the CLI -- the same real, unmocked
OpenCascade pipeline, expressed as Gherkin per the project's test plan.
"""

from __future__ import annotations

from pathlib import Path

from pytest_bdd import given, parsers, scenarios, then, when

from flipfill import commands
from flipfill.geometry.exporters import export_shape
from flipfill.geometry.generator import fit_envelope_to_objects, generate
from flipfill.geometry.importers import GeometryRepository
from flipfill.model import (
    ClearanceMode,
    ObjectRole,
    PrimitiveKind,
    Project,
    SliceCutterKind,
    Transform,
    Vector3,
)

scenarios("features/slicing.feature")


@given(
    "a new project with a rounded-box envelope sized like a handheld case",
    target_fixture="ctx",
)
def _new_project(tmp_path: Path) -> dict:
    project = Project(name="BDD Case")
    project.envelope.kind = PrimitiveKind.ROUNDED_BOX
    project.envelope.radius = 6.0
    return {"project": project, "tmp_path": tmp_path, "repository": GeometryRepository()}


@given("a screen, a battery, and mounting screws positioned inside it")
def _add_occupants(ctx: dict) -> None:
    project: Project = ctx["project"]
    commands.add_primitive_object(
        project,
        role=ObjectRole.OCCUPANT,
        kind=PrimitiveKind.ROUNDED_BOX,
        size=Vector3(70.0, 110.0, 4.0),
        radius=2.0,
        translation=Vector3(0, 0, 6),
        name="Screen",
        clearance_mode=ClearanceMode.AABB,
        clearance_mm=0.5,
    )
    commands.add_primitive_object(
        project,
        role=ObjectRole.OCCUPANT,
        kind=PrimitiveKind.ROUNDED_BOX,
        size=Vector3(60.0, 90.0, 6.0),
        radius=2.0,
        translation=Vector3(0, 0, -6),
        name="Battery",
        clearance_mode=ClearanceMode.AABB,
        clearance_mm=0.5,
    )
    for x, y in [(-32, 58), (32, 58), (-32, -58), (32, -58)]:
        commands.add_primitive_object(
            project,
            role=ObjectRole.OCCUPANT,
            kind=PrimitiveKind.CYLINDER,
            size=Vector3(3.0, 3.0, 20.0),
            translation=Vector3(x, y, 0),
            name=f"Screw ({x}, {y})",
            clearance_mode=ClearanceMode.AABB,
            clearance_mm=0.2,
        )
    fit_envelope_to_objects(project, ctx["repository"])


@when("the project is generated")
def _generate_first(ctx: dict) -> None:
    ctx["generated"] = generate(ctx["project"], ctx["repository"])


@then("generation succeeds with no errors")
def _assert_no_errors(ctx: dict) -> None:
    assert ctx["generated"].errors == []


@when(parsers.parse('I add a horizontal slice named "{name}" near the front face'))
def _add_front_slice(ctx: dict, name: str) -> None:
    # slice_result() carves each named piece from the local -Z side of its
    # cutter plane and feeds the +Z side forward as the remainder, so
    # sequential plane cuts must use strictly increasing Z -- this slice is
    # applied first, so it takes the lower of the two cutter heights even
    # though it is named for the "front" (higher) face.
    project: Project = ctx["project"]
    top_z = project.envelope.transform.translation.z + project.envelope.size.z / 2.0
    commands.add_slice(
        project,
        name=name,
        cutter_kind=SliceCutterKind.PLANE,
        transform=Transform(translation=Vector3(0, 0, top_z - 10.0)),
    )


@when(parsers.parse('I add a horizontal slice named "{name}" further back'))
def _add_second_slice(ctx: dict, name: str) -> None:
    project: Project = ctx["project"]
    top_z = project.envelope.transform.translation.z + project.envelope.size.z / 2.0
    commands.add_slice(
        project,
        name=name,
        cutter_kind=SliceCutterKind.PLANE,
        transform=Transform(translation=Vector3(0, 0, top_z - 3.0)),
    )


@when("the project is generated again with slicing enabled")
def _generate_second(ctx: dict) -> None:
    commands.configure_slicing(ctx["project"], enabled=True)
    ctx["generated"] = generate(ctx["project"], ctx["repository"])


@then(parsers.parse("generation produces exactly {count:d} bodies"))
def _assert_body_count(ctx: dict, count: int) -> None:
    assert len(ctx["generated"].sliced_bodies) == count


@then("every produced body is a valid, positive-volume solid")
def _assert_bodies_valid(ctx: dict) -> None:
    for shape in ctx["generated"].sliced_bodies.values():
        assert shape.isValid()
        assert shape.Volume() > 0


@then(parsers.parse('the bodies are named "{a}", "{b}", and "{c}"'))
def _assert_body_names(ctx: dict, a: str, b: str, c: str) -> None:
    assert set(ctx["generated"].sliced_bodies) == {a, b, c}


@then("every body's STEP export opens as a valid solid")
def _assert_export_round_trip(ctx: dict) -> None:
    repository = GeometryRepository()
    for index, (_name, shape) in enumerate(ctx["generated"].sliced_bodies.items()):
        path = ctx["tmp_path"] / f"body_{index}.step"
        export_shape(shape, path)
        resolved = repository.load(path)
        assert resolved.brep is not None
        assert resolved.brep.isValid()
        assert resolved.brep.Volume() > 0
