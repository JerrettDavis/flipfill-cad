from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum

import cadquery as cq

from flipfill.geometry.bounds import Bounds3D, bounds_from_shape
from flipfill.geometry.importers import GeometryRepository, ResolvedGeometry
from flipfill.geometry.offsets import OffsetError, offset_shape
from flipfill.geometry.primitives import make_aabb, make_primitive
from flipfill.model import (
    ClearanceMode,
    ObjectRole,
    PrimitiveKind,
    PrimitiveSpec,
    Project,
    SceneObject,
    SplitAxis,
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
    split_a: cq.Shape | None = None
    split_b: cq.Shape | None = None

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


def _subtractive_shape(
    scene_object: SceneObject,
    resolved: ResolvedGeometry,
    project: Project,
    messages: list[GenerationMessage],
) -> cq.Shape:
    if resolved.brep is None:
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


def _fuse_many(base: cq.Shape, shapes: list[cq.Shape], tolerance: float) -> cq.Shape:
    result = base
    for shape in shapes:
        result = result.fuse(shape, tol=tolerance)
    return result.clean()


def _cut_many(base: cq.Shape, shapes: list[cq.Shape], tolerance: float) -> cq.Shape:
    result = base
    for shape in shapes:
        result = result.cut(shape, tol=tolerance)
    return result.clean()


def generate(project: Project, repository: GeometryRepository | None = None) -> GenerationResult:
    repository = repository or GeometryRepository()
    messages: list[GenerationMessage] = []
    envelope = envelope_shape(project)
    generated_objects: list[GeneratedObject] = []
    cavities: list[cq.Shape] = []
    cutouts: list[cq.Shape] = []
    additives: list[cq.Shape] = []

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
                cavities.append(boolean_shape)
            else:
                cutouts.append(boolean_shape)
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
                additives.append(resolved.brep)

    if any(message.level is MessageLevel.ERROR for message in messages):
        raise GenerationError(
            "Generation cannot continue because one or more scene objects failed to resolve"
        )

    try:
        result = _fuse_many(envelope, additives, project.boolean_tolerance)
        result = _cut_many(result, cavities + cutouts, project.boolean_tolerance)
    except Exception as exc:
        raise GenerationError(f"Boolean generation failed: {exc}") from exc

    if result.isNull():
        raise GenerationError("Boolean generation produced a null shape")

    generated = GenerationResult(
        envelope=envelope,
        result=result,
        objects=generated_objects,
        cavity_shapes=cavities,
        cutout_shapes=cutouts,
        additive_shapes=additives,
        messages=messages,
    )

    generated.messages.extend(validate_generation(project, generated))

    if project.split.enabled:
        try:
            generated.split_a, generated.split_b = split_shape(
                generated.result,
                project.split.axis,
                project.split.offset,
                project.split.gap,
                project.boolean_tolerance,
            )
        except Exception as exc:
            generated.messages.append(
                GenerationMessage(MessageLevel.ERROR, f"Split operation failed: {exc}")
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


def split_shape(
    shape: cq.Shape,
    axis: SplitAxis,
    offset: float,
    gap: float = 0.0,
    tolerance: float = 1.0e-4,
) -> tuple[cq.Shape, cq.Shape]:
    bounds = bounds_from_shape(shape)
    low_plane = offset - max(0.0, gap) / 2.0
    high_plane = offset + max(0.0, gap) / 2.0
    padding = max(bounds.size.x, bounds.size.y, bounds.size.z, 1.0) + 10.0

    mins = [bounds.minimum.x - padding, bounds.minimum.y - padding, bounds.minimum.z - padding]
    maxs = [bounds.maximum.x + padding, bounds.maximum.y + padding, bounds.maximum.z + padding]
    axis_index = {SplitAxis.X: 0, SplitAxis.Y: 1, SplitAxis.Z: 2}[axis]

    if not mins[axis_index] < low_plane < maxs[axis_index]:
        raise GenerationError("Lower split plane lies outside the generated body bounds")
    if not mins[axis_index] < high_plane < maxs[axis_index]:
        raise GenerationError("Upper split plane lies outside the generated body bounds")

    low_min = mins.copy()
    low_max = maxs.copy()
    low_max[axis_index] = low_plane

    high_min = mins.copy()
    high_min[axis_index] = high_plane
    high_max = maxs.copy()

    def clipping_box(minimum: list[float], maximum: list[float]) -> cq.Shape:
        size = Vector3(
            maximum[0] - minimum[0],
            maximum[1] - minimum[1],
            maximum[2] - minimum[2],
        )
        center = Vector3(
            (minimum[0] + maximum[0]) / 2.0,
            (minimum[1] + maximum[1]) / 2.0,
            (minimum[2] + maximum[2]) / 2.0,
        )
        return make_aabb(size, center)

    low = shape.intersect(clipping_box(low_min, low_max), tol=tolerance).clean()
    high = shape.intersect(clipping_box(high_min, high_max), tol=tolerance).clean()
    if low.isNull() or high.isNull():
        raise GenerationError("Split produced an empty half")
    return low, high
