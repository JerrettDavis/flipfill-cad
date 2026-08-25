from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from flipfill.model import Project


class ProjectIoError(RuntimeError):
    pass


def load_project(path: str | Path) -> Project:
    project_path = Path(path).expanduser().resolve()
    try:
        data = json.loads(project_path.read_text(encoding="utf-8"))
        project = Project.from_dict(data)
    except Exception as exc:
        raise ProjectIoError(f"Could not load project {project_path}: {exc}") from exc

    for scene_object in project.objects:
        if not scene_object.source_path:
            continue
        source = Path(scene_object.source_path).expanduser()
        if not source.is_absolute():
            source = (project_path.parent / source).resolve()
        scene_object.source_path = str(source)
    return project


def save_project(project: Project, path: str | Path) -> Path:
    project_path = Path(path).expanduser().resolve()
    project_path.parent.mkdir(parents=True, exist_ok=True)
    data = project.to_dict()

    serialized_objects: list[dict[str, Any]] = []
    for scene_object, object_data in zip(project.objects, data["objects"], strict=True):
        if scene_object.source_path:
            source = Path(scene_object.source_path).expanduser().resolve()
            try:
                object_data["source_path"] = str(source.relative_to(project_path.parent))
            except ValueError:
                object_data["source_path"] = str(source)
        serialized_objects.append(object_data)
    data["objects"] = serialized_objects

    try:
        project_path.write_text(
            json.dumps(data, indent=2, sort_keys=False) + "\n", encoding="utf-8"
        )
    except Exception as exc:
        raise ProjectIoError(f"Could not save project {project_path}: {exc}") from exc
    return project_path
