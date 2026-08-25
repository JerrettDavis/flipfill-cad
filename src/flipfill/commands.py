"""Application service layer shared by the CLI and, eventually, the desktop UI.

Every function here operates on plain ``flipfill.model`` types and raises
:class:`CommandError` for user-facing problems (bad references, invalid
enum values, out-of-range numbers). It performs no console I/O and no
``sys.exit`` calls, so it can be unit-tested directly and reused from any
front end without duplicating validation or geometry logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from flipfill.geometry.align import AlignError, axis_index, bound_value
from flipfill.geometry.bounds import Bounds3D
from flipfill.geometry.generator import fit_envelope_to_objects
from flipfill.geometry.importers import GeometryRepository, ImportGeometryError
from flipfill.model import (
    ClearanceMode,
    EnvelopeSpec,
    ObjectRole,
    PrimitiveKind,
    PrimitiveSpec,
    Project,
    SceneObject,
    SplitAxis,
    Transform,
    Vector3,
)
from flipfill.project_io import ProjectIoError, load_project, save_project


class CommandError(RuntimeError):
    """A user-facing error: bad reference, invalid value, or ambiguous input."""


# ----------------------------------------------------------------------
# Project lifecycle
# ----------------------------------------------------------------------


def create_project(path: str | Path, name: str | None = None, units: str = "mm") -> Path:
    """Create and save a new, empty project file. Refuses to overwrite."""

    project_path = Path(path).expanduser().resolve()
    if project_path.exists():
        raise CommandError(f"Refusing to overwrite existing file: {project_path}")
    project = Project(name=name or project_path.stem, units=units)
    return save_project(project, project_path)


def open_project(path: str | Path) -> Project:
    try:
        return load_project(path)
    except ProjectIoError as exc:
        raise CommandError(str(exc)) from exc


# ----------------------------------------------------------------------
# Object lookup
# ----------------------------------------------------------------------


def find_object(project: Project, ref: str) -> SceneObject:
    """Resolve ``ref`` to a single scene object by id or, failing that, by name."""

    by_id = project.object_by_id(ref)
    if by_id is not None:
        return by_id

    matches = [obj for obj in project.objects if obj.name == ref]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise CommandError(
            f"No object matches id or name {ref!r}. Use 'flipfill list' to see available objects."
        )
    ids = ", ".join(obj.id for obj in matches)
    raise CommandError(
        f"{len(matches)} objects are named {ref!r}; use one of these ids instead: {ids}"
    )


# ----------------------------------------------------------------------
# Import
# ----------------------------------------------------------------------


def import_geometry(
    project: Project,
    repository: GeometryRepository,
    sources: list[str],
    role: ObjectRole = ObjectRole.OCCUPANT,
    name: str | None = None,
    clearance_mode: ClearanceMode = ClearanceMode.AABB,
    clearance_mm: float = 0.5,
) -> list[SceneObject]:
    """Import one or more CAD/mesh files as new scene objects.

    Each file is resolved immediately so import failures surface before the
    project is saved; nothing is added to the project for a file that fails.
    """

    if not sources:
        raise CommandError("At least one source file is required")
    if len(sources) > 1 and name:
        raise CommandError("--name can only be used when importing a single file")

    added: list[SceneObject] = []
    failures: list[str] = []
    for source in sources:
        source_path = Path(source).expanduser()
        if not source_path.exists():
            failures.append(f"{source}: file does not exist")
            continue
        scene_object = SceneObject(
            name=name or source_path.stem,
            source_path=str(source_path.resolve()),
            role=role,
            clearance_mode=clearance_mode,
            clearance_mm=clearance_mm,
            included_in_envelope_fit=role is not ObjectRole.CUTOUT,
        )
        try:
            repository.resolve(scene_object)
        except ImportGeometryError as exc:
            failures.append(f"{source}: {exc}")
            continue
        project.objects.append(scene_object)
        added.append(scene_object)

    if failures:
        raise CommandError(
            f"Imported {len(added)} of {len(sources)} file(s); failures:\n"
            + "\n".join(f"  - {failure}" for failure in failures)
        )
    return added


# ----------------------------------------------------------------------
# Listing / inspection
# ----------------------------------------------------------------------


def summarize_object(scene_object: SceneObject) -> dict[str, Any]:
    return {
        "id": scene_object.id,
        "name": scene_object.name,
        "role": scene_object.role.value,
        "kind": scene_object.geometry_kind.value,
        "source_path": scene_object.source_path,
        "visible": scene_object.visible,
        "included_in_envelope_fit": scene_object.included_in_envelope_fit,
        "clearance_mode": scene_object.clearance_mode.value,
        "clearance_mm": scene_object.clearance_mm,
        "translation": scene_object.transform.translation.to_list(),
        "rotation_deg": scene_object.transform.rotation_deg.to_list(),
    }


def list_objects(project: Project) -> list[dict[str, Any]]:
    return [summarize_object(obj) for obj in project.objects]


@dataclass(slots=True)
class ObjectInspection:
    summary: dict[str, Any]
    bounds: Bounds3D | None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = dict(self.summary)
        if self.bounds is not None:
            data["bounds"] = {
                "min": self.bounds.minimum.to_list(),
                "max": self.bounds.maximum.to_list(),
                "size": self.bounds.size.to_list(),
                "center": self.bounds.center.to_list(),
            }
        if self.error:
            data["resolve_error"] = self.error
        return data


def inspect_object(
    project: Project, repository: GeometryRepository, ref: str
) -> ObjectInspection:
    scene_object = find_object(project, ref)
    summary = summarize_object(scene_object)
    if scene_object.primitive is not None:
        summary["primitive"] = scene_object.primitive.to_dict()
    try:
        resolved = repository.resolve(scene_object)
        return ObjectInspection(summary=summary, bounds=resolved.bounds)
    except Exception as exc:  # geometry resolution failures are user-facing here
        return ObjectInspection(summary=summary, bounds=None, error=str(exc))


# ----------------------------------------------------------------------
# Transform
# ----------------------------------------------------------------------


def move_object(
    scene_object: SceneObject, x: float, y: float, z: float, relative: bool = False
) -> None:
    if relative:
        scene_object.transform.translation = scene_object.transform.translation + Vector3(x, y, z)
    else:
        scene_object.transform.translation = Vector3(x, y, z)


def rotate_object(
    scene_object: SceneObject, x: float, y: float, z: float, relative: bool = False
) -> None:
    if relative:
        scene_object.transform.rotation_deg = scene_object.transform.rotation_deg + Vector3(
            x, y, z
        )
    else:
        scene_object.transform.rotation_deg = Vector3(x, y, z)


def set_role(scene_object: SceneObject, role: ObjectRole) -> None:
    scene_object.role = role


def set_clearance(
    scene_object: SceneObject, mode: ClearanceMode | None, mm: float | None
) -> None:
    if mode is not None:
        scene_object.clearance_mode = mode
    if mm is not None:
        if mm < 0:
            raise CommandError("Clearance must be zero or positive")
        scene_object.clearance_mm = mm


# ----------------------------------------------------------------------
# Alignment
# ----------------------------------------------------------------------


def align_object(
    project: Project,
    repository: GeometryRepository,
    scene_object: SceneObject,
    axis: str,
    mode: str,
    target_ref: str | None = None,
) -> None:
    """Align one axis of ``scene_object``'s bounds to a target's bounds or the origin.

    ``mode`` is one of ``min`` (low face), ``max`` (high face), or ``center``.
    ``target_ref`` names another object to align against; omit it to align to
    the origin (0 on the chosen axis).
    """

    try:
        index = axis_index(axis)
    except AlignError as exc:
        raise CommandError(str(exc)) from exc
    if mode not in {"min", "max", "center"}:
        raise CommandError(f"Align mode must be one of min, max, center (got {mode!r})")

    source_bounds = repository.resolve(scene_object).bounds

    if target_ref is None:
        target_value = 0.0
    else:
        target_object = find_object(project, target_ref)
        if target_object.id == scene_object.id:
            raise CommandError("An object cannot be aligned to itself")
        target_bounds = repository.resolve(target_object).bounds
        target_value = bound_value(target_bounds, axis, mode)

    source_value = bound_value(source_bounds, axis, mode)
    delta = target_value - source_value

    translation = scene_object.transform.translation.to_list()
    translation[index] += delta
    scene_object.transform.translation = Vector3(*translation)


# ----------------------------------------------------------------------
# Primitives (blockers / additives / occupant proxies)
# ----------------------------------------------------------------------

_DEFAULT_CLEARANCE_BY_ROLE = {
    ObjectRole.OCCUPANT: (ClearanceMode.AABB, 0.5),
    ObjectRole.CUTOUT: (ClearanceMode.EXACT, 0.0),
    ObjectRole.ADDITIVE: (ClearanceMode.EXACT, 0.0),
    ObjectRole.REFERENCE: (ClearanceMode.EXACT, 0.0),
}


def add_primitive_object(
    project: Project,
    role: ObjectRole,
    kind: PrimitiveKind,
    size: Vector3,
    radius: float = 0.0,
    translation: Vector3 | None = None,
    rotation_deg: Vector3 | None = None,
    name: str | None = None,
    clearance_mode: ClearanceMode | None = None,
    clearance_mm: float | None = None,
    include_in_envelope_fit: bool | None = None,
) -> SceneObject:
    default_mode, default_clearance = _DEFAULT_CLEARANCE_BY_ROLE[role]
    scene_object = SceneObject(
        name=name or role.value.capitalize(),
        role=role,
        primitive=PrimitiveSpec(kind=kind, size=size, radius=radius),
        transform=Transform(
            translation=translation or Vector3(),
            rotation_deg=rotation_deg or Vector3(),
        ),
        clearance_mode=clearance_mode or default_mode,
        clearance_mm=default_clearance if clearance_mm is None else clearance_mm,
        included_in_envelope_fit=(
            role is not ObjectRole.CUTOUT
            if include_in_envelope_fit is None
            else include_in_envelope_fit
        ),
    )
    project.objects.append(scene_object)
    return scene_object


# ----------------------------------------------------------------------
# Envelope
# ----------------------------------------------------------------------


def configure_envelope(
    project: Project,
    kind: PrimitiveKind | None = None,
    size: Vector3 | None = None,
    translation: Vector3 | None = None,
    rotation_deg: Vector3 | None = None,
    radius: float | None = None,
    fit_margin: Vector3 | None = None,
) -> EnvelopeSpec:
    envelope = project.envelope
    if kind is not None:
        envelope.kind = kind
    if size is not None:
        envelope.size = size
    if translation is not None:
        envelope.transform.translation = translation
    if rotation_deg is not None:
        envelope.transform.rotation_deg = rotation_deg
    if radius is not None:
        envelope.radius = radius
    if fit_margin is not None:
        envelope.fit_margin = fit_margin
    return envelope


def fit_envelope(
    project: Project,
    repository: GeometryRepository,
    object_ids: list[str] | None = None,
) -> Bounds3D:
    return fit_envelope_to_objects(project, repository, object_ids)


# ----------------------------------------------------------------------
# Split
# ----------------------------------------------------------------------


def configure_split(
    project: Project,
    enabled: bool | None = None,
    axis: SplitAxis | None = None,
    offset: float | None = None,
    gap: float | None = None,
) -> None:
    split = project.split
    if enabled is not None:
        split.enabled = enabled
    if axis is not None:
        split.axis = axis
    if offset is not None:
        split.offset = offset
    if gap is not None:
        if gap < 0:
            raise CommandError("Split gap must be zero or positive")
        split.gap = gap


# ----------------------------------------------------------------------
# Doctor
# ----------------------------------------------------------------------


@dataclass(slots=True)
class DoctorCheck:
    name: str
    ok: bool
    detail: str


@dataclass(slots=True)
class DoctorReport:
    checks: list[DoctorCheck] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "checks": [
                {"name": c.name, "ok": c.ok, "detail": c.detail} for c in self.checks
            ],
        }


def run_doctor() -> DoctorReport:
    import sys

    report = DoctorReport()

    report.checks.append(
        DoctorCheck("python", True, f"Python {sys.version.split()[0]} at {sys.executable}")
    )

    try:
        import cadquery

        report.checks.append(
            DoctorCheck(
                "cadquery",
                True,
                f"cadquery {getattr(cadquery, '__version__', 'unknown')}",
            )
        )
    except Exception as exc:
        report.checks.append(DoctorCheck("cadquery", False, f"not importable: {exc}"))

    try:
        import OCP  # noqa: F401

        report.checks.append(DoctorCheck("OCP (OpenCascade bindings)", True, "importable"))
    except Exception as exc:
        report.checks.append(
            DoctorCheck("OCP (OpenCascade bindings)", False, f"not importable: {exc}")
        )

    try:
        import trimesh

        report.checks.append(
            DoctorCheck(
                "trimesh",
                True,
                f"trimesh {getattr(trimesh, '__version__', 'unknown')}",
            )
        )
    except Exception as exc:
        report.checks.append(DoctorCheck("trimesh", False, f"not importable: {exc}"))

    try:
        import vtkmodules  # noqa: F401

        report.checks.append(DoctorCheck("VTK", True, "importable"))
    except Exception as exc:
        report.checks.append(DoctorCheck("VTK", False, f"not importable: {exc}"))

    try:
        import tkinter

        root = tkinter.Tk()
        root.destroy()
        report.checks.append(DoctorCheck("Tk display", True, "a Tk root window was created"))
    except Exception as exc:
        report.checks.append(
            DoctorCheck(
                "Tk display",
                False,
                f"could not create a Tk window ({exc}); the desktop GUI needs a display "
                "(on Linux, run under Xvfb or a real X/Wayland session). The CLI does not "
                "need this.",
            )
        )

    try:
        from flipfill.rendering import SceneRenderer

        scene = SceneRenderer(width=64, height=64)
        scene.render_to_image(64, 64)
        report.checks.append(
            DoctorCheck("Off-screen rendering", True, "produced a test frame")
        )
    except Exception as exc:
        report.checks.append(
            DoctorCheck(
                "Off-screen rendering",
                False,
                f"'flipfill render' and viewport previews will fail: {exc}",
            )
        )

    return report
