from __future__ import annotations

import json
from pathlib import Path

import cadquery as cq
import pytest
from cadquery import exporters

from flipfill.cli import main
from flipfill.project_io import load_project


def _step_asset(tmp_path: Path, name: str, size: tuple[float, float, float]) -> Path:
    path = tmp_path / name
    exporters.export(cq.Workplane("XY").box(*size), str(path))
    return path


def test_new_creates_project(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    project_path = tmp_path / "demo.flipfill.json"

    code = main(["new", str(project_path), "--name", "Demo"])

    assert code == 0
    assert project_path.exists()
    loaded = load_project(project_path)
    assert loaded.name == "Demo"
    assert "Created project" in capsys.readouterr().out


def test_new_refuses_overwrite_without_force(tmp_path: Path) -> None:
    project_path = tmp_path / "demo.flipfill.json"
    assert main(["new", str(project_path)]) == 0

    code = main(["new", str(project_path)])

    assert code != 0
    assert main(["new", str(project_path), "--force"]) == 0


def test_new_json_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    project_path = tmp_path / "demo.flipfill.json"

    assert main(["new", str(project_path), "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert Path(payload["path"]) == project_path


def test_import_list_and_inspect(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    project_path = tmp_path / "demo.flipfill.json"
    asset = _step_asset(tmp_path, "battery.step", (10, 8, 6))
    main(["new", str(project_path)])
    capsys.readouterr()

    code = main(
        [
            "import",
            str(project_path),
            str(asset),
            "--role",
            "occupant",
            "--name",
            "Battery",
        ]
    )
    assert code == 0
    capsys.readouterr()

    assert main(["list", str(project_path), "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)["objects"]
    assert len(rows) == 1
    assert rows[0]["name"] == "Battery"
    assert rows[0]["role"] == "occupant"

    assert main(["inspect", str(project_path), "Battery", "--json"]) == 0
    detail = json.loads(capsys.readouterr().out)
    assert detail["name"] == "Battery"
    assert detail["bounds"]["size"] == pytest.approx([10.0, 8.0, 6.0])


def test_import_missing_file_fails(tmp_path: Path) -> None:
    project_path = tmp_path / "demo.flipfill.json"
    main(["new", str(project_path)])

    code = main(["import", str(project_path), str(tmp_path / "missing.step")])

    assert code != 0


def test_move_rotate_role_clearance(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    project_path = tmp_path / "demo.flipfill.json"
    asset = _step_asset(tmp_path, "part.step", (10, 8, 6))
    main(["new", str(project_path)])
    main(["import", str(project_path), str(asset), "--name", "Part"])
    capsys.readouterr()

    assert main(["move", str(project_path), "Part", "--x", "1", "--y", "2", "--z", "3"]) == 0
    assert main(["rotate", str(project_path), "Part", "--x", "0", "--y", "0", "--z", "90"]) == 0
    assert main(["role", str(project_path), "Part", "cutout"]) == 0
    assert (
        main(
            [
                "clearance",
                str(project_path),
                "Part",
                "--mode",
                "offset",
                "--mm",
                "0.6",
            ]
        )
        == 0
    )

    project = load_project(project_path)
    obj = project.objects[0]
    assert obj.transform.translation.to_list() == [1.0, 2.0, 3.0]
    assert obj.transform.rotation_deg.to_list() == [0.0, 0.0, 90.0]
    assert obj.role.value == "cutout"
    assert obj.clearance_mode.value == "offset"
    assert obj.clearance_mm == pytest.approx(0.6)


def test_move_relative_is_additive(tmp_path: Path) -> None:
    project_path = tmp_path / "demo.flipfill.json"
    asset = _step_asset(tmp_path, "part.step", (10, 8, 6))
    main(["new", str(project_path)])
    main(["import", str(project_path), str(asset), "--name", "Part"])
    main(["move", str(project_path), "Part", "--x", "1", "--y", "1", "--z", "1"])

    assert (
        main(
            [
                "move",
                str(project_path),
                "Part",
                "--x",
                "1",
                "--y",
                "0",
                "--z",
                "0",
                "--relative",
            ]
        )
        == 0
    )

    project = load_project(project_path)
    assert project.objects[0].transform.translation.to_list() == [2.0, 1.0, 1.0]


def test_align_to_origin_and_object(tmp_path: Path) -> None:
    project_path = tmp_path / "demo.flipfill.json"
    left = _step_asset(tmp_path, "left.step", (10, 10, 10))
    right = _step_asset(tmp_path, "right.step", (4, 4, 4))
    main(["new", str(project_path)])
    main(["import", str(project_path), str(left), "--name", "Left"])
    main(["import", str(project_path), str(right), "--name", "Right"])
    main(["move", str(project_path), "Right", "--x", "50", "--y", "0", "--z", "0"])

    code = main(
        ["align", str(project_path), "Right", "--axis", "x", "--mode", "center", "--to", "Left"]
    )

    assert code == 0
    project = load_project(project_path)
    right_obj = project.object_by_id(
        next(o.id for o in project.objects if o.name == "Right")
    )
    assert right_obj is not None
    assert right_obj.transform.translation.x == pytest.approx(0.0, abs=1.0e-6)


def test_align_unknown_object_fails(tmp_path: Path) -> None:
    project_path = tmp_path / "demo.flipfill.json"
    asset = _step_asset(tmp_path, "part.step", (10, 8, 6))
    main(["new", str(project_path)])
    main(["import", str(project_path), str(asset), "--name", "Part"])

    code = main(["align", str(project_path), "Part", "--axis", "x", "--mode", "center", "--to", "Ghost"])

    assert code != 0


def test_blocker_and_envelope_fit(tmp_path: Path) -> None:
    project_path = tmp_path / "demo.flipfill.json"
    asset = _step_asset(tmp_path, "part.step", (10, 8, 6))
    main(["new", str(project_path)])
    main(["import", str(project_path), str(asset), "--name", "Part"])

    assert (
        main(
            [
                "blocker",
                str(project_path),
                "--role",
                "cutout",
                "--kind",
                "box",
                "--size",
                "4",
                "3",
                "3",
            ]
        )
        == 0
    )
    assert main(["envelope", str(project_path), "--fit", "--margin", "2", "2", "2"]) == 0

    project = load_project(project_path)
    assert any(obj.role.value == "cutout" for obj in project.objects)
    assert project.envelope.size.x > 10.0


def test_split_configure(tmp_path: Path) -> None:
    project_path = tmp_path / "demo.flipfill.json"
    main(["new", str(project_path)])

    assert (
        main(
            [
                "split",
                str(project_path),
                "--enable",
                "--axis",
                "z",
                "--offset",
                "1.5",
                "--gap",
                "0.3",
            ]
        )
        == 0
    )

    project = load_project(project_path)
    assert project.split.enabled is True
    assert project.split.axis.value == "z"
    assert project.split.offset == pytest.approx(1.5)
    assert project.split.gap == pytest.approx(0.3)


def test_generate_validate_and_export(tmp_path: Path) -> None:
    project_path = tmp_path / "demo.flipfill.json"
    asset = _step_asset(tmp_path, "part.step", (10, 8, 6))
    main(["new", str(project_path)])
    main(["import", str(project_path), str(asset), "--name", "Part", "--clearance-mode", "aabb"])
    main(["envelope", str(project_path), "--fit", "--margin", "3", "3", "3"])

    assert main(["validate", str(project_path)]) == 0

    output = tmp_path / "out.step"
    assert main(["generate", str(project_path), "-o", str(output)]) == 0
    assert output.exists() and output.stat().st_size > 0

    export_path = tmp_path / "export.stl"
    assert (
        main(["export", str(project_path), str(export_path), "--target", "stl"]) == 0
    )
    assert export_path.exists() and export_path.stat().st_size > 0


def test_validate_missing_project_returns_nonzero(tmp_path: Path) -> None:
    code = main(["validate", str(tmp_path / "missing.flipfill.json")])

    assert code != 0


def test_doctor_reports_ok(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["doctor", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["ok"] is True
    assert any(check["name"] == "cadquery" for check in payload["checks"])


def test_missing_command_argument_exits_nonzero() -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["move"])

    assert excinfo.value.code not in (0, None)


def test_unknown_role_choice_exits_nonzero(tmp_path: Path) -> None:
    project_path = tmp_path / "demo.flipfill.json"
    asset = _step_asset(tmp_path, "part.step", (10, 8, 6))
    main(["new", str(project_path)])
    main(["import", str(project_path), str(asset), "--name", "Part"])

    with pytest.raises(SystemExit) as excinfo:
        main(["role", str(project_path), "Part", "not-a-real-role"])

    assert excinfo.value.code not in (0, None)
