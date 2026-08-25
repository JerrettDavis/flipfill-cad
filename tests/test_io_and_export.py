from __future__ import annotations

from pathlib import Path

import cadquery as cq
from cadquery import exporters

from flipfill.geometry.exporters import export_fitcheck_assembly, export_shape
from flipfill.geometry.generator import generate
from flipfill.geometry.importers import GeometryRepository
from flipfill.model import (
    ObjectRole,
    PrimitiveKind,
    Project,
    SceneObject,
    Vector3,
)
from flipfill.project_io import load_project, save_project


def test_project_paths_round_trip_relative(tmp_path: Path) -> None:
    asset = tmp_path / "part.step"
    exporters.export(cq.Workplane("XY").box(5, 6, 7), str(asset))
    project = Project(name="Path test")
    project.objects.append(SceneObject(name="part", source_path=str(asset)))
    project_path = tmp_path / "test.flipfill.json"

    save_project(project, project_path)
    loaded = load_project(project_path)

    assert Path(loaded.objects[0].source_path or "") == asset.resolve()
    assert "part.step" in project_path.read_text(encoding="utf-8")


def test_step_import_generate_and_export(tmp_path: Path) -> None:
    source = tmp_path / "source.step"
    exporters.export(cq.Workplane("XY").box(10, 8, 6), str(source))
    project = Project(name="Import export")
    project.envelope.kind = PrimitiveKind.BOX
    project.envelope.size = Vector3(20, 20, 20)
    project.objects.append(
        SceneObject(name="part", source_path=str(source), role=ObjectRole.OCCUPANT)
    )

    repository = GeometryRepository()
    generated = generate(project, repository)
    output = export_shape(generated.result, tmp_path / "result.step")
    fitcheck = export_fitcheck_assembly(
        project, generated, tmp_path / "fitcheck.step"
    )

    assert output.exists() and output.stat().st_size > 0
    assert fitcheck.exists() and fitcheck.stat().st_size > 0
    reloaded = repository.load(output)
    assert reloaded.brep is not None
    assert reloaded.brep.isValid()


def test_mesh_import_uses_aabb_for_boolean(tmp_path: Path) -> None:
    source = tmp_path / "mesh.stl"
    exporters.export(cq.Workplane("XY").box(10, 8, 6), str(source))
    project = Project(name="Mesh")
    project.envelope.kind = PrimitiveKind.BOX
    project.envelope.size = Vector3(20, 20, 20)
    project.objects.append(
        SceneObject(name="mesh", source_path=str(source), role=ObjectRole.OCCUPANT)
    )

    generated = generate(project, GeometryRepository())

    assert generated.result.Volume() < 20**3
    assert not generated.errors
