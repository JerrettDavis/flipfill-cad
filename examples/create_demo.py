from __future__ import annotations

from pathlib import Path

import cadquery as cq
from cadquery import exporters

from flipfill.geometry.exporters import export_fitcheck_assembly, export_shape
from flipfill.geometry.generator import fit_envelope_to_objects, generate
from flipfill.geometry.importers import GeometryRepository
from flipfill.geometry.primitives import make_primitive
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
from flipfill.project_io import save_project

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "assets"
ASSETS.mkdir(parents=True, exist_ok=True)


def rounded(size: Vector3, radius: float, translation: Vector3 | None = None) -> cq.Shape:
    return make_primitive(
        PrimitiveSpec(PrimitiveKind.ROUNDED_BOX, size, radius),
        Transform(translation=translation if translation is not None else Vector3()),
    )


def build_assets() -> None:
    board = rounded(Vector3(54.5, 101.5, 1.6), 3.5)
    touch = rounded(Vector3(50.0, 76.0, 3.5), 2.0, Vector3(0, -2, -2.55))
    rear_components = rounded(Vector3(47.0, 80.0, 3.0), 2.0, Vector3(0, 2, 2.3))
    display = board.fuse(touch).fuse(rear_components).clean()
    exporters.export(display, str(ASSETS / "demo_display_module.step"))

    battery = rounded(Vector3(48.0, 60.0, 8.0), 3.0)
    exporters.export(battery, str(ASSETS / "demo_battery.step"))

    speaker = cq.Workplane("XY").cylinder(5.0, 14.0, centered=True).val()
    exporters.export(speaker, str(ASSETS / "demo_speaker.step"))


def build_project() -> Project:
    project = Project(name="Portable Touch Monitor Demo")
    project.envelope.kind = PrimitiveKind.ROUNDED_BOX
    project.envelope.radius = 6.0
    project.envelope.fit_margin = Vector3(4.0, 4.0, 3.0)

    project.objects.extend(
        [
            SceneObject(
                name="3.5in Display Module",
                source_path=str(ASSETS / "demo_display_module.step"),
                role=ObjectRole.OCCUPANT,
                clearance_mode=ClearanceMode.AABB,
                clearance_mm=0.6,
            ),
            SceneObject(
                name="LiPo Battery",
                source_path=str(ASSETS / "demo_battery.step"),
                role=ObjectRole.OCCUPANT,
                transform=Transform(translation=Vector3(0, 15, 9.5)),
                clearance_mode=ClearanceMode.AABB,
                clearance_mm=0.7,
            ),
            SceneObject(
                name="Speaker",
                source_path=str(ASSETS / "demo_speaker.step"),
                role=ObjectRole.OCCUPANT,
                transform=Transform(translation=Vector3(0, -33, 8.0)),
                clearance_mode=ClearanceMode.OFFSET,
                clearance_mm=0.5,
            ),
            SceneObject(
                name="Screen Opening",
                role=ObjectRole.CUTOUT,
                primitive=PrimitiveSpec(
                    PrimitiveKind.ROUNDED_BOX, Vector3(49.0, 75.0, 10.0), 2.0
                ),
                transform=Transform(translation=Vector3(0, -2, -7.0)),
                clearance_mode=ClearanceMode.EXACT,
                clearance_mm=0,
                included_in_envelope_fit=False,
            ),
            SceneObject(
                name="USB-C Side Access",
                role=ObjectRole.CUTOUT,
                primitive=PrimitiveSpec(PrimitiveKind.ROUNDED_BOX, Vector3(14, 10, 8), 2),
                transform=Transform(translation=Vector3(30.5, 35, 1.5)),
                clearance_mode=ClearanceMode.EXACT,
                clearance_mm=0,
                included_in_envelope_fit=False,
            ),
            SceneObject(
                name="Button Access",
                role=ObjectRole.CUTOUT,
                primitive=PrimitiveSpec(PrimitiveKind.BOX, Vector3(10, 12, 8)),
                transform=Transform(translation=Vector3(-30.5, 35, 1.5)),
                clearance_mode=ClearanceMode.EXACT,
                clearance_mm=0,
                included_in_envelope_fit=False,
            ),
            SceneObject(
                name="Speaker Grille Opening",
                role=ObjectRole.CUTOUT,
                primitive=PrimitiveSpec(PrimitiveKind.CYLINDER, Vector3(24, 24, 10)),
                transform=Transform(translation=Vector3(0, -33, 14.0)),
                clearance_mode=ClearanceMode.EXACT,
                clearance_mm=0,
                included_in_envelope_fit=False,
            ),
            SceneObject(
                name="Lanyard Channel",
                role=ObjectRole.CUTOUT,
                primitive=PrimitiveSpec(PrimitiveKind.CYLINDER, Vector3(5, 5, 12)),
                transform=Transform(translation=Vector3(27, -47, 6.0)),
                clearance_mode=ClearanceMode.EXACT,
                clearance_mm=0,
                included_in_envelope_fit=False,
            ),
        ]
    )

    repository = GeometryRepository()
    fit_envelope_to_objects(project, repository)
    project.slicing.enabled = True
    project.slicing.slices.append(
        SliceSpec(
            name="Bottom Shell",
            cutter_kind=SliceCutterKind.PLANE,
            transform=Transform(translation=Vector3(0, 0, 1.5)),
            gap=0.35,
        )
    )
    project.slicing.remainder_name = "Top Shell"
    return project


def main() -> None:
    build_assets()
    project = build_project()
    project_path = ROOT / "portable_monitor_demo.flipfill.json"
    save_project(project, project_path)

    result = generate(project, GeometryRepository())
    export_shape(result.result, ROOT / "portable_monitor_demo.step")
    export_fitcheck_assembly(
        project, result, ROOT / "portable_monitor_demo_fitcheck.step"
    )
    for name, shape in result.sliced_bodies.items():
        slug = "".join(c.lower() if c.isalnum() else "_" for c in name).strip("_")
        export_shape(shape, ROOT / f"portable_monitor_demo_{slug}.step")

    print(project_path)
    print(f"Generated volume: {result.result.Volume():.3f} mm^3")
    for message in result.messages:
        print(message.level.value.upper(), message.message)


if __name__ == "__main__":
    main()
