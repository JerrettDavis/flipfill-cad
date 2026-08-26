"""True end-to-end workflow tests driven entirely through the public CLI.

Each test creates a project, imports hardware, positions and classifies it,
fits an envelope, generates and validates the enclosure, optionally slices
it, exports STEP, and reopens the project/outputs to verify what was
actually written to disk -- the same sequence a real user's shell script
would run.
"""

from __future__ import annotations

import json
from pathlib import Path

import cadquery as cq
import pytest
from cadquery import exporters

from flipfill.cli import main
from flipfill.geometry.importers import GeometryRepository
from flipfill.project_io import load_project


def _step_asset(tmp_path: Path, name: str, size: tuple[float, float, float]) -> Path:
    path = tmp_path / name
    exporters.export(cq.Workplane("XY").box(*size), str(path))
    return path


def test_full_enclosure_workflow(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    project_path = tmp_path / "case.flipfill.json"
    board = _step_asset(tmp_path, "board.step", (54.0, 30.0, 1.6))
    battery = _step_asset(tmp_path, "battery.step", (30.0, 20.0, 6.0))

    # 1. Create the project.
    assert main(["new", str(project_path), "--name", "E2E Case"]) == 0

    # 2. Import hardware as occupants with distinct clearance strategies.
    assert (
        main(
            [
                "import",
                str(project_path),
                str(board),
                "--role",
                "occupant",
                "--name",
                "Board",
                "--clearance-mode",
                "aabb",
                "--clearance",
                "0.4",
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "import",
                str(project_path),
                str(battery),
                "--role",
                "occupant",
                "--name",
                "Battery",
                "--clearance-mode",
                "aabb",
                "--clearance",
                "0.5",
            ]
        )
        == 0
    )

    # 3. Position the stack so nothing overlaps.
    assert main(["move", str(project_path), "Board", "--x", "0", "--y", "0", "--z", "-3"]) == 0
    assert (
        main(["move", str(project_path), "Battery", "--x", "0", "--y", "0", "--z", "3"]) == 0
    )

    # 4. Add a cutout blocker that bridges through the envelope wall.
    assert (
        main(
            [
                "blocker",
                str(project_path),
                "--role",
                "cutout",
                "--kind",
                "box",
                "--name",
                "USB Access",
                "--size",
                "10",
                "6",
                "6",
                "--at-x",
                "27",
                "--at-y",
                "0",
                "--at-z",
                "0",
            ]
        )
        == 0
    )

    # 5. Fit the envelope around the whole stack.
    assert (
        main(["envelope", str(project_path), "--fit", "--margin", "4", "4", "4"]) == 0
    )

    # 6. Add a plane slice and enable slicing.
    assert (
        main(
            [
                "slice",
                str(project_path),
                "add",
                "--name",
                "Bottom",
                "--plane",
                "--at-z",
                "0",
                "--gap",
                "0.3",
            ]
        )
        == 0
    )
    assert main(["slice", str(project_path), "enable"]) == 0

    # 7. Validate before export -- must report no errors (no unintended
    # intersections between the occupants, cutout, and generated body).
    capsys.readouterr()
    assert main(["validate", str(project_path), "--json"]) == 0
    validation = json.loads(capsys.readouterr().out)
    assert validation["ok"] is True
    assert validation["errors"] == []
    assert validation["valid"] is True
    assert validation["volume_mm3"] > 0

    # 8. Generate and export STEP, the fit-check assembly, and sliced bodies.
    output = tmp_path / "out" / "case.step"
    fitcheck = tmp_path / "out" / "case_fitcheck.step"
    slice_dir = tmp_path / "out"
    assert (
        main(
            [
                "generate",
                str(project_path),
                "-o",
                str(output),
                "--fitcheck",
                str(fitcheck),
                "--slice-dir",
                str(slice_dir),
            ]
        )
        == 0
    )
    assert output.exists() and output.stat().st_size > 0
    assert fitcheck.exists() and fitcheck.stat().st_size > 0
    slice_bottom = slice_dir / "case_bottom.step"
    slice_remainder = slice_dir / "case_remainder.step"
    assert slice_bottom.exists() and slice_bottom.stat().st_size > 0
    assert slice_remainder.exists() and slice_remainder.stat().st_size > 0

    # 9. Reopen the saved project from disk and verify what was persisted.
    reloaded = load_project(project_path)
    assert reloaded.name == "E2E Case"
    assert {o.name for o in reloaded.objects} == {"Board", "Battery", "USB Access"}
    assert reloaded.slicing.enabled is True

    # 10. Reimport every exported STEP artifact and verify it is a valid,
    # non-degenerate solid.
    repository = GeometryRepository()
    for artifact in (output, fitcheck, slice_bottom, slice_remainder):
        resolved = repository.load(artifact)
        assert resolved.brep is not None
        assert resolved.brep.isValid()
        assert resolved.brep.Volume() > 0

    # The two sliced pieces are strictly smaller than the whole body: the
    # configured 0.3mm kerf gap removes a thin slab between them.
    body = repository.load(output).brep
    bottom = repository.load(slice_bottom).brep
    remainder = repository.load(slice_remainder).brep
    assert 0 < bottom.Volume() + remainder.Volume() < body.Volume()


def test_workflow_reports_overlapping_occupants(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Placing two occupants so they overlap must be surfaced by validate."""

    project_path = tmp_path / "collision.flipfill.json"
    a = _step_asset(tmp_path, "a.step", (20.0, 20.0, 20.0))
    b = _step_asset(tmp_path, "b.step", (20.0, 20.0, 20.0))

    main(["new", str(project_path)])
    main(["import", str(project_path), str(a), "--name", "A"])
    main(["import", str(project_path), str(b), "--name", "B"])
    # Leave both objects at the origin -- fully overlapping.
    main(["envelope", str(project_path), "--fit", "--margin", "5", "5", "5"])
    capsys.readouterr()

    code = main(["validate", str(project_path), "--json"])
    validation = json.loads(capsys.readouterr().out)

    # Overlapping occupant clearances are reported as a warning (never
    # silently ignored) so a user positioning hardware sees it, without
    # blocking generation for the common touching-faces case.
    assert code == 0
    assert validation["ok"] is True
    assert any("overlaps" in warning for warning in validation["warnings"])
