from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum

import cadquery as cq

from flipfill.geometry.bounds import Bounds3D, bounds_from_shape, obb_from_vertices
from flipfill.geometry.importers import GeometryRepository, ResolvedGeometry
from flipfill.geometry.offsets import OffsetError, offset_shape
from flipfill.geometry.primitives import make_aabb, make_primitive
from flipfill.geometry.tessellation import tessellate_shape
from flipfill.geometry.transforms import transform_shape
from flipfill.model import (
    ClearanceMode,
    ObjectRole,
    PrimitiveKind,
    PrimitiveSpec,
    Project,
    SceneObject,
    SliceCutterKind,
    SliceSpec,
    SlicingSpec,
    Transform,
    Vector3,
)


class MessageLevel(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(slots=True)
class GenerationMessage:
    level: MessageLevel
    message: str
    object_id: str | None = None


@dataclass(slots=True)
class GeneratedObject:
    scene_object: SceneObject
    resolved: ResolvedGeometry
    boolean_shape: cq.Shape | None = None


@dataclass(slots=True)
class GenerationResult:
    envelope: cq.Shape
    result: cq.Shape
    objects: list[GeneratedObject]
    cavity_shapes: list[cq.Shape]
    cutout_shapes: list[cq.Shape]
    additive_shapes: list[cq.Shape]
    messages: list[GenerationMessage] = field(default_factory=list)
    sliced_bodies: dict[str, cq.Shape] = field(default_factory=dict)

    @property
    def errors(self) -> list[GenerationMessage]:
        return [m for m in self.messages if m.level is MessageLevel.ERROR]

    @property
    def warnings(self) -> list[GenerationMessage]:
        return [m for m in self.messages if m.level is MessageLevel.WARNING]


class GenerationError(RuntimeError):
    pass


def envelope_shape(project: Project) -> cq.Shape:
    return make_primitive(
        PrimitiveSpec(
            kind=project.envelope.kind,
            size=project.envelope.size,
            radius=project.envelope.radius,
        ),
        project.envelope.transform,
    )


def fit_envelope_to_objects(
    project: Project,
    repository: GeometryRepository,
    object_ids: Iterable[str] | None = None,
) -> Bounds3D:
    requested = set(object_ids) if object_ids is not None else None
    bounds: list[Bounds3D] = []

    for scene_object in project.objects:
        if requested is not None and scene_object.id not in requested:
            continue
        if requested is None and not scene_object.included_in_envelope_fit:
            continue
        if scene_object.role in {ObjectRole.CUTOUT, ObjectRole.RESULT}:
            continue
        resolved = repository.resolve(scene_object)
        bounds.append(resolved.bounds)

    if not bounds:
        raise GenerationError("No eligible objects are available for envelope fitting")

    fitted = Bounds3D.union(bounds).expanded(project.envelope.fit_margin)
    project.envelope.size = fitted.size
    project.envelope.transform.translation = fitted.center
    # Auto-fit is explicitly world-axis-aligned in 0.1. Retaining an earlier
    # envelope rotation would make the fitted dimensions lie about containment
    # and can clip otherwise valid hardware after generation.
    project.envelope.transform.rotation_deg = Vector3()

    # Keep the radius legal after a very small fit.
    if project.envelope.kind is PrimitiveKind.ROUNDED_BOX:
        maximum = max(0.0, min(fitted.size.x, fitted.size.y) / 2.0 - 1.0e-3)
        project.envelope.radius = min(project.envelope.radius, maximum)

    return fitted


def _aabb_clearance(resolved: ResolvedGeometry, clearance: float) -> cq.Shape:
    expanded = resolved.bounds.expanded(max(0.0, clearance))
    return make_aabb(expanded.size, expanded.center)


def _obb_clearance_from_vertices(vertices, clearance: float) -> cq.Shape:
    obb = obb_from_vertices(vertices).expanded(max(0.0, clearance))
    return make_primitive(
        PrimitiveSpec(kind=PrimitiveKind.BOX, size=obb.size),
        Transform(translation=obb.center, rotation_deg=obb.rotation_deg),
    )


def _obb_clearance(
    resolved: ResolvedGeometry, clearance: float, tessellation_tolerance: float
) -> cq.Shape:
    if resolved.mesh_vertices is not None:
        vertices = resolved.mesh_vertices
    else:
        assert resolved.brep is not None
        vertices = tessellate_shape(resolved.brep, tessellation_tolerance, 0.1).vertices
    return _obb_clearance_from_vertices(vertices, clearance)


def _subtractive_shape(
    scene_object: SceneObject,
    resolved: ResolvedGeometry,
    project: Project,
    messages: list[GenerationMessage],
) -> cq.Shape:
    if resolved.brep is None:
        if scene_object.clearance_mode is ClearanceMode.OBB:
            return _obb_clearance(resolved, scene_object.clearance_mm, project.tessellation_tolerance)
        if scene_object.clearance_mode is not ClearanceMode.AABB:
            messages.append(
                GenerationMessage(
                    MessageLevel.WARNING,
                    "Mesh objects cannot participate in exact BRep subtraction; "
                    "using their transformed axis-aligned bounding box instead.",
                    scene_object.id,
                )
            )
        return _aabb_clearance(resolved, scene_object.clearance_mm)

    if scene_object.clearance_mode is ClearanceMode.EXACT:
        return resolved.brep
    if scene_object.clearance_mode is ClearanceMode.AABB:
        return _aabb_clearance(resolved, scene_object.clearance_mm)
    if scene_object.clearance_mode is ClearanceMode.OBB:
        return _obb_clearance(resolved, scene_object.clearance_mm, project.tessellation_tolerance)

    try:
        return offset_shape(
            resolved.brep,
            max(0.0, scene_object.clearance_mm),
            tolerance=project.boolean_tolerance,
        )
    except OffsetError as exc:
        messages.append(
            GenerationMessage(
                MessageLevel.WARNING,
                f"Exact clearance offset failed ({exc}); using an expanded AABB fallback.",
                scene_object.id,
            )
        )
        return _aabb_clearance(resolved, scene_object.clearance_mm)


def _owner_label(owner: SceneObject | SliceSpec) -> str:
    if isinstance(owner, SceneObject):
        return f"'{owner.name}' ({owner.role.value})"
    return f"slice '{owner.name}'"


def _owner_id(owner: SceneObject | SliceSpec) -> str | None:
    return owner.id if isinstance(owner, SceneObject) else None


def _boolean_step(
    op: str,
    result: cq.Shape,
    shape: cq.Shape,
    owner: SceneObject | SliceSpec,
    tolerance: float,
    messages: list[GenerationMessage],
) -> cq.Shape:
    """Apply one fuse/cut/intersect step, retrying once after a topology
    cleanup pass.

    OCCT Booleans can fail on otherwise-valid inputs because of small
    numerical artifacts (sliver faces, duplicate edges) in one operand.
    Retrying with both sides ``.clean()``-ed first recovers a real fraction
    of those failures; when it doesn't, the resulting error names the
    specific object/slice responsible instead of a generic "Boolean
    generation failed", so a user knows what to fix.
    """

    method = getattr(result, op)
    try:
        return method(shape, tol=tolerance)
    except Exception as first_exc:
        try:
            cleaned_result = result.clean()
            cleaned_shape = shape.clean()
            recovered = getattr(cleaned_result, op)(cleaned_shape, tol=tolerance)
        except Exception as exc:
            raise GenerationError(
                f"{op.capitalize()} failed while combining {_owner_label(owner)}: {exc}"
            ) from exc
        messages.append(
            GenerationMessage(
                MessageLevel.WARNING,
                f"{op.capitalize()} with {_owner_label(owner)} needed a topology cleanup "
                f"pass to succeed ({first_exc}); the result may warrant a closer look.",
                _owner_id(owner),
            )
        )
        return recovered


def _fuse_many(
    base: cq.Shape,
    shapes: list[tuple[cq.Shape, SceneObject]],
    tolerance: float,
    messages: list[GenerationMessage],
) -> cq.Shape:
    result = base
    for shape, scene_object in shapes:
        result = _boolean_step("fuse", result, shape, scene_object, tolerance, messages)
    return result.clean()


def _cut_many(
    base: cq.Shape,
    shapes: list[tuple[cq.Shape, SceneObject]],
    tolerance: float,
    messages: list[GenerationMessage],
) -> cq.Shape:
    result = base
    for shape, scene_object in shapes:
        result = _boolean_step("cut", result, shape, scene_object, tolerance, messages)
    return result.clean()


def _local_box(size_x: float, size_y: float, z_min: float, z_max: float) -> cq.Shape:
    """A box spanning [-size_x/2, size_x/2] x [-size_y/2, size_y/2] x
    [z_min, z_max] in local coordinates, ready to be positioned by a
    Transform via transform_shape -- used to build a knife whose local
    z=0 plane is the cutter's own plane, before it is rotated/translated
    into world space."""
    size_z = z_max - z_min
    box = cq.Workplane("XY").box(size_x, size_y, size_z, centered=True).val()
    return box.translate((0.0, 0.0, (z_min + z_max) / 2.0))


def _plane_knives(
    transform: Transform, gap: float, bounds: Bounds3D
) -> tuple[cq.Shape, cq.Shape]:
    """Two knife solids for one plane cut: the first isolates the piece
    carved off (local -Z side), the second is what gets removed from the
    remainder going forward. They differ only when ``gap`` (kerf) is
    nonzero, matching the ``low_plane``/``high_plane`` split of the
    now-removed ``split_shape``, generalized from a world axis to an
    arbitrary oriented plane."""

    padding = max(bounds.size.x, bounds.size.y, bounds.size.z, 1.0) + 10.0
    half_gap = max(0.0, gap) / 2.0
    size_xy = 2.0 * padding
    piece_knife = _local_box(size_xy, size_xy, -padding, -half_gap)
    remainder_knife = _local_box(size_xy, size_xy, -padding, half_gap)
    return transform_shape(piece_knife, transform), transform_shape(remainder_knife, transform)


def _object_knife(
    slice_spec: SliceSpec, repository: GeometryRepository, project: Project
) -> cq.Shape:
    if not slice_spec.object_id:
        raise GenerationError(f"Slice '{slice_spec.name}' has no object reference")
    scene_object = project.object_by_id(slice_spec.object_id)
    if scene_object is None:
        raise GenerationError(
            f"Slice '{slice_spec.name}' references a missing object id "
            f"{slice_spec.object_id!r}"
        )
    resolved = repository.resolve(scene_object)
    if resolved.brep is None:
        raise GenerationError(
            f"Slice '{slice_spec.name}' references '{scene_object.name}', which has no "
            "BRep geometry; mesh-only objects cannot be used as a cutting tool."
        )
    return resolved.brep


def slice_result(
    result: cq.Shape,
    slicing: SlicingSpec,
    repository: GeometryRepository,
    project: Project,
    tolerance: float,
    messages: list[GenerationMessage],
) -> dict[str, cq.Shape]:
    bodies: dict[str, cq.Shape] = {}
    remainder = result
    bounds = bounds_from_shape(result)
    for slice_spec in slicing.slices:
        if slice_spec.cutter_kind is SliceCutterKind.PLANE:
            piece_knife, remainder_knife = _plane_knives(
                slice_spec.transform, slice_spec.gap, bounds
            )
        else:
            piece_knife = remainder_knife = _object_knife(slice_spec, repository, project)
        piece = _boolean_step(
            "intersect", remainder, piece_knife, slice_spec, tolerance, messages
        )
        remainder = _boolean_step(
            "cut", remainder, remainder_knife, slice_spec, tolerance, messages
        )
        if piece.isNull() or piece.Volume() <= tolerance:
            raise GenerationError(f"Slice '{slice_spec.name}' produced an empty body")
        bodies[slice_spec.name] = piece.clean()
    if remainder.isNull() or remainder.Volume() <= tolerance:
        raise GenerationError("Slicing consumed the entire body; the remainder is empty")
    bodies[slicing.remainder_name] = remainder.clean()
    return bodies


def generate(project: Project, repository: GeometryRepository | None = None) -> GenerationResult:
    repository = repository or GeometryRepository()
    messages: list[GenerationMessage] = []
    envelope = envelope_shape(project)
    generated_objects: list[GeneratedObject] = []
    cavities: list[tuple[cq.Shape, SceneObject]] = []
    cutouts: list[tuple[cq.Shape, SceneObject]] = []
    additives: list[tuple[cq.Shape, SceneObject]] = []

    for scene_object in project.objects:
        try:
            resolved = repository.resolve(scene_object)
        except Exception as exc:
            messages.append(
                GenerationMessage(
                    MessageLevel.ERROR,
                    f"Could not resolve geometry: {exc}",
                    scene_object.id,
                )
            )
            continue

        generated = GeneratedObject(scene_object=scene_object, resolved=resolved)
        generated_objects.append(generated)

        if scene_object.role is ObjectRole.REFERENCE:
            continue
        if scene_object.role is ObjectRole.RESULT:
            continue
        if scene_object.role in {ObjectRole.OCCUPANT, ObjectRole.CUTOUT}:
            boolean_shape = _subtractive_shape(
                scene_object, resolved, project, messages
            )
            generated.boolean_shape = boolean_shape
            if scene_object.role is ObjectRole.OCCUPANT:
                cavities.append((boolean_shape, scene_object))
            else:
                cutouts.append((boolean_shape, scene_object))
            continue
        if scene_object.role is ObjectRole.ADDITIVE:
            if resolved.brep is None:
                messages.append(
                    GenerationMessage(
                        MessageLevel.ERROR,
                        "Mesh geometry cannot be fused into a STEP BRep. Convert it to a "
                        "solid STEP/BREP or replace it with a primitive.",
                        scene_object.id,
                    )
                )
            else:
                generated.boolean_shape = resolved.brep
                additives.append((resolved.brep, scene_object))

    if any(message.level is MessageLevel.ERROR for message in messages):
        raise GenerationError(
            "Generation cannot continue because one or more scene objects failed to resolve"
        )

    result = _fuse_many(envelope, additives, project.boolean_tolerance, messages)
    result = _cut_many(result, cavities + cutouts, project.boolean_tolerance, messages)

    if result.isNull():
        raise GenerationError("Boolean generation produced a null shape")

    generated = GenerationResult(
        envelope=envelope,
        result=result,
        objects=generated_objects,
        cavity_shapes=[shape for shape, _ in cavities],
        cutout_shapes=[shape for shape, _ in cutouts],
        additive_shapes=[shape for shape, _ in additives],
        messages=messages,
    )

    generated.messages.extend(validate_generation(project, generated))

    if project.slicing.enabled:
        generated.sliced_bodies = slice_result(
            generated.result,
            project.slicing,
            repository,
            project,
            project.boolean_tolerance,
            generated.messages,
        )

    return generated


def validate_generation(
    project: Project, generated: GenerationResult
) -> list[GenerationMessage]:
    messages: list[GenerationMessage] = []
    envelope_bounds = bounds_from_shape(generated.envelope)

    if not generated.result.isValid():
        messages.append(
            GenerationMessage(MessageLevel.ERROR, "Generated body is not a valid BRep")
        )

    try:
        if generated.result.Volume() <= project.boolean_tolerance:
            messages.append(
                GenerationMessage(
                    MessageLevel.ERROR, "Generated body has zero or negligible volume"
                )
            )
    except Exception:
        messages.append(
            GenerationMessage(
                MessageLevel.WARNING,
                "Could not calculate generated volume; inspect the exported fit-check assembly.",
            )
        )

    occupant_objects = [
        obj for obj in generated.objects if obj.scene_object.role is ObjectRole.OCCUPANT
    ]
    for generated_object in occupant_objects:
        cavity = generated_object.boolean_shape
        if cavity is None:
            continue
        object_bounds = bounds_from_shape(cavity)
        if not envelope_bounds.contains(object_bounds, tolerance=project.boolean_tolerance):
            messages.append(
                GenerationMessage(
                    MessageLevel.WARNING,
                    "Occupant clearance volume extends outside the envelope. This may be "
                    "intentional at a screen face, but should be verified.",
                    generated_object.scene_object.id,
                )
            )
        try:
            residual_volume = generated.result.intersect(
                cavity, tol=project.boolean_tolerance
            ).Volume()
            if residual_volume > max(1.0e-5, project.boolean_tolerance * 10.0):
                messages.append(
                    GenerationMessage(
                        MessageLevel.ERROR,
                        f"Generated material intersects this occupant cavity by "
                        f"{residual_volume:.6f} mm³.",
                        generated_object.scene_object.id,
                    )
                )
        except Exception as exc:
            messages.append(
                GenerationMessage(
                    MessageLevel.WARNING,
                    f"Could not verify cavity/result intersection: {exc}",
                    generated_object.scene_object.id,
                )
            )

    # Occupant/occupant intersections indicate a bad placement before an enclosure
    # is generated. Touching faces have zero volume and are not reported.
    for index, left in enumerate(occupant_objects):
        if left.boolean_shape is None:
            continue
        for right in occupant_objects[index + 1 :]:
            if right.boolean_shape is None:
                continue
            try:
                overlap = left.boolean_shape.intersect(
                    right.boolean_shape, tol=project.boolean_tolerance
                ).Volume()
            except Exception:
                continue
            if overlap > 1.0e-4:
                messages.append(
                    GenerationMessage(
                        MessageLevel.WARNING,
                        f"Occupant clearance overlaps '{right.scene_object.name}' by "
                        f"{overlap:.3f} mm³; verify the physical stack.",
                        left.scene_object.id,
                    )
                )

    for generated_object in (
        obj for obj in generated.objects if obj.scene_object.role is ObjectRole.CUTOUT
    ):
        cutout = generated_object.boolean_shape
        if cutout is None:
            continue
        try:
            intersection = generated.envelope.intersect(
                cutout, tol=project.boolean_tolerance
            ).Volume()
            if intersection <= 1.0e-6:
                messages.append(
                    GenerationMessage(
                        MessageLevel.WARNING,
                        "Cutout blocker does not intersect the envelope and therefore removes nothing.",
                        generated_object.scene_object.id,
                    )
                )
        except Exception:
            pass

    return messages
