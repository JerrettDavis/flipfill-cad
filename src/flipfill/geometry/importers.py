from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cadquery as cq
import numpy as np
from cadquery import importers
from OCP.IFSelect import IFSelect_RetDone
from OCP.IGESControl import IGESControl_Reader

from flipfill.geometry.bounds import Bounds3D, bounds_from_shape, bounds_from_vertices
from flipfill.geometry.primitives import make_primitive
from flipfill.geometry.transforms import transform_shape, transform_vertices
from flipfill.model import GeometryKind, SceneObject


class ImportGeometryError(RuntimeError):
    pass


@dataclass(slots=True)
class LoadedGeometry:
    kind: GeometryKind
    source_path: Path | None
    brep: cq.Shape | None = None
    mesh_vertices: np.ndarray | None = None
    mesh_faces: np.ndarray | None = None

    @property
    def is_brep(self) -> bool:
        return self.brep is not None

    @property
    def is_mesh(self) -> bool:
        return self.mesh_vertices is not None and self.mesh_faces is not None


@dataclass(slots=True)
class ResolvedGeometry:
    object_id: str
    kind: GeometryKind
    brep: cq.Shape | None
    mesh_vertices: np.ndarray | None
    mesh_faces: np.ndarray | None
    bounds: Bounds3D


_BREP_SUFFIXES = {".step", ".stp", ".brep", ".brp", ".iges", ".igs"}
_MESH_SUFFIXES = {".stl", ".obj", ".ply", ".off", ".3mf", ".glb", ".gltf"}


class GeometryRepository:
    """Caches immutable source geometry and resolves transformed scene bodies."""

    def __init__(self) -> None:
        self._cache: dict[Path, LoadedGeometry] = {}

    def clear(self) -> None:
        self._cache.clear()

    def load(self, path: str | Path) -> LoadedGeometry:
        resolved = Path(path).expanduser().resolve()
        if not resolved.exists():
            raise ImportGeometryError(f"Geometry file does not exist: {resolved}")
        cached = self._cache.get(resolved)
        if cached is not None:
            return cached

        suffix = resolved.suffix.lower()
        if suffix in _BREP_SUFFIXES:
            loaded = self._load_brep(resolved)
        elif suffix in _MESH_SUFFIXES:
            loaded = self._load_mesh(resolved)
        else:
            raise ImportGeometryError(
                f"Unsupported geometry format '{suffix}'. Supported BRep formats: "
                f"{', '.join(sorted(_BREP_SUFFIXES))}; mesh reference formats: "
                f"{', '.join(sorted(_MESH_SUFFIXES))}"
            )

        self._cache[resolved] = loaded
        return loaded

    def resolve(self, scene_object: SceneObject) -> ResolvedGeometry:
        if scene_object.primitive is not None:
            shape = make_primitive(scene_object.primitive, scene_object.transform)
            return ResolvedGeometry(
                object_id=scene_object.id,
                kind=GeometryKind.PRIMITIVE,
                brep=shape,
                mesh_vertices=None,
                mesh_faces=None,
                bounds=bounds_from_shape(shape),
            )

        if not scene_object.source_path:
            raise ImportGeometryError(
                f"Scene object '{scene_object.name}' has neither a source file nor a primitive"
            )

        loaded = self.load(scene_object.source_path)
        if loaded.brep is not None:
            shape = transform_shape(loaded.brep, scene_object.transform)
            return ResolvedGeometry(
                object_id=scene_object.id,
                kind=loaded.kind,
                brep=shape,
                mesh_vertices=None,
                mesh_faces=None,
                bounds=bounds_from_shape(shape),
            )

        assert loaded.mesh_vertices is not None
        assert loaded.mesh_faces is not None
        vertices = transform_vertices(loaded.mesh_vertices, scene_object.transform)
        return ResolvedGeometry(
            object_id=scene_object.id,
            kind=loaded.kind,
            brep=None,
            mesh_vertices=vertices,
            mesh_faces=loaded.mesh_faces.copy(),
            bounds=bounds_from_vertices(vertices),
        )

    @staticmethod
    def supported_file_patterns() -> tuple[tuple[str, str], ...]:
        return (
            ("CAD and mesh files", "*.step *.stp *.brep *.brp *.iges *.igs *.stl *.obj *.ply *.off *.3mf *.glb *.gltf"),
            ("STEP", "*.step *.stp"),
            ("IGES", "*.iges *.igs"),
            ("BREP", "*.brep *.brp"),
            ("Mesh references", "*.stl *.obj *.ply *.off *.3mf *.glb *.gltf"),
            ("All files", "*.*"),
        )

    def _load_brep(self, path: Path) -> LoadedGeometry:
        suffix = path.suffix.lower()
        try:
            if suffix in {".step", ".stp"}:
                shape = importers.importStep(str(path)).val()
            elif suffix in {".brep", ".brp"}:
                shape = importers.importBrep(str(path)).val()
            else:
                reader = IGESControl_Reader()
                status = reader.ReadFile(str(path))
                if status != IFSelect_RetDone:
                    raise ImportGeometryError(
                        f"OpenCascade could not read IGES file: {path} (status {status})"
                    )
                if reader.TransferRoots() == 0:
                    raise ImportGeometryError(f"IGES file contains no transferable roots: {path}")
                shape = cq.Shape(reader.OneShape())
        except ImportGeometryError:
            raise
        except Exception as exc:  # pragma: no cover - error text varies by OCCT build
            raise ImportGeometryError(f"Failed to import {path}: {exc}") from exc

        if shape is None or shape.isNull():
            raise ImportGeometryError(f"Imported file produced an empty shape: {path}")
        return LoadedGeometry(kind=GeometryKind.BREP, source_path=path, brep=shape)

    def _load_mesh(self, path: Path) -> LoadedGeometry:
        try:
            import trimesh

            loaded: Any = trimesh.load(str(path), force="scene", process=False)
            if isinstance(loaded, trimesh.Scene):
                geometries = [g for g in loaded.geometry.values() if len(g.vertices)]
                if not geometries:
                    raise ImportGeometryError(f"Mesh scene contains no geometry: {path}")
                mesh = trimesh.util.concatenate(geometries)
            else:
                mesh = loaded
            vertices = np.asarray(mesh.vertices, dtype=float)
            faces = np.asarray(mesh.faces, dtype=np.int64)
        except ImportGeometryError:
            raise
        except Exception as exc:
            raise ImportGeometryError(f"Failed to import mesh {path}: {exc}") from exc

        if vertices.size == 0 or faces.size == 0:
            raise ImportGeometryError(f"Mesh contains no triangles: {path}")
        return LoadedGeometry(
            kind=GeometryKind.MESH,
            source_path=path,
            mesh_vertices=vertices,
            mesh_faces=faces,
        )
