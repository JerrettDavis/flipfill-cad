"""Malformed-input and error-path tests for the model and project I/O layer.

These cover failure modes a real user hits often -- a hand-edited or
corrupted project file, an unsupported schema version, a bad enum value --
and assert they fail with a clear, catchable error rather than an
unhandled traceback or (worse) silently wrong data.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from flipfill.model import ClearanceMode, ObjectRole, Project, Vector3
from flipfill.project_io import ProjectIoError, load_project, save_project


def test_load_project_missing_file_raises_project_io_error(tmp_path: Path) -> None:
    with pytest.raises(ProjectIoError):
        load_project(tmp_path / "does_not_exist.flipfill.json")


def test_load_project_invalid_json_raises_project_io_error(tmp_path: Path) -> None:
    path = tmp_path / "broken.flipfill.json"
    path.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(ProjectIoError):
        load_project(path)


def test_load_project_unsupported_schema_version_raises(tmp_path: Path) -> None:
    path = tmp_path / "future.flipfill.json"
    path.write_text(json.dumps({"schema_version": 999}), encoding="utf-8")

    with pytest.raises(ProjectIoError):
        load_project(path)


def test_load_project_unknown_role_raises(tmp_path: Path) -> None:
    path = tmp_path / "bad_role.flipfill.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "objects": [{"id": "a", "name": "a", "role": "not-a-real-role"}],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ProjectIoError):
        load_project(path)


def test_load_project_empty_object_defaults_cleanly(tmp_path: Path) -> None:
    """A minimal object dict must fall back to safe defaults, not crash."""

    path = tmp_path / "minimal.flipfill.json"
    path.write_text(
        json.dumps({"schema_version": 1, "objects": [{}]}), encoding="utf-8"
    )

    project = load_project(path)

    assert len(project.objects) == 1
    obj = project.objects[0]
    assert obj.role is ObjectRole.OCCUPANT
    assert obj.clearance_mode is ClearanceMode.AABB


def test_vector3_from_value_rejects_wrong_length() -> None:
    with pytest.raises(ValueError):
        Vector3.from_value([1, 2])


def test_vector3_from_value_rejects_wrong_type() -> None:
    with pytest.raises(ValueError):
        Vector3.from_value("not-a-vector")


def test_save_project_creates_parent_directories(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b" / "c" / "project.flipfill.json"

    saved = save_project(Project(name="Nested"), nested)

    assert saved.exists()
    assert load_project(saved).name == "Nested"


def test_project_from_dict_missing_objects_key_defaults_to_empty() -> None:
    project = Project.from_dict({"schema_version": 1})

    assert project.objects == []
    assert project.name  # falls back to a sensible default, never blank/None
