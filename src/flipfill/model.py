from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4


class ObjectRole(str, Enum):
    """How an object participates in inverse-fill generation."""

    OCCUPANT = "occupant"
    CUTOUT = "cutout"
    ADDITIVE = "additive"
    REFERENCE = "reference"
    RESULT = "result"


class ClearanceMode(str, Enum):
    """How an occupant is expanded before subtraction."""

    EXACT = "exact"
    OFFSET = "offset"
    AABB = "aabb"


class PrimitiveKind(str, Enum):
    BOX = "box"
    ROUNDED_BOX = "rounded_box"
    CYLINDER = "cylinder"
    SLOT = "slot"


class GeometryKind(str, Enum):
    BREP = "brep"
    MESH = "mesh"
    PRIMITIVE = "primitive"


class SplitAxis(str, Enum):
    X = "x"
    Y = "y"
    Z = "z"


@dataclass(slots=True)
class Vector3:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

    def to_list(self) -> list[float]:
        return [float(self.x), float(self.y), float(self.z)]

    @classmethod
    def from_value(cls, value: Any, default: "Vector3 | None" = None) -> "Vector3":
        if value is None:
            return default or cls()
        if isinstance(value, cls):
            return value
        if isinstance(value, dict):
            return cls(
                float(value.get("x", 0.0)),
                float(value.get("y", 0.0)),
                float(value.get("z", 0.0)),
            )
        if isinstance(value, (list, tuple)) and len(value) == 3:
            return cls(float(value[0]), float(value[1]), float(value[2]))
        raise ValueError(f"Expected a 3-vector, got {value!r}")

    def __add__(self, other: "Vector3") -> "Vector3":
        return Vector3(self.x + other.x, self.y + other.y, self.z + other.z)

    def __sub__(self, other: "Vector3") -> "Vector3":
        return Vector3(self.x - other.x, self.y - other.y, self.z - other.z)

    def scaled(self, factor: float) -> "Vector3":
        return Vector3(self.x * factor, self.y * factor, self.z * factor)


@dataclass(slots=True)
class Transform:
    translation: Vector3 = field(default_factory=Vector3)
    rotation_deg: Vector3 = field(default_factory=Vector3)

    def to_dict(self) -> dict[str, Any]:
        return {
            "translation": self.translation.to_list(),
            "rotation_deg": self.rotation_deg.to_list(),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "Transform":
        value = value or {}
        return cls(
            translation=Vector3.from_value(value.get("translation")),
            rotation_deg=Vector3.from_value(value.get("rotation_deg")),
        )


@dataclass(slots=True)
class PrimitiveSpec:
    kind: PrimitiveKind = PrimitiveKind.BOX
    size: Vector3 = field(default_factory=lambda: Vector3(20.0, 20.0, 20.0))
    radius: float = 2.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "size": self.size.to_list(),
            "radius": float(self.radius),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "PrimitiveSpec":
        return cls(
            kind=PrimitiveKind(value.get("kind", PrimitiveKind.BOX.value)),
            size=Vector3.from_value(value.get("size"), Vector3(20.0, 20.0, 20.0)),
            radius=float(value.get("radius", 2.0)),
        )


@dataclass(slots=True)
class SceneObject:
    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = "Object"
    role: ObjectRole = ObjectRole.OCCUPANT
    transform: Transform = field(default_factory=Transform)
    source_path: str | None = None
    primitive: PrimitiveSpec | None = None
    visible: bool = True
    included_in_envelope_fit: bool = True
    clearance_mode: ClearanceMode = ClearanceMode.AABB
    clearance_mm: float = 0.5
    color: tuple[float, float, float] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def geometry_kind(self) -> GeometryKind:
        if self.primitive is not None:
            return GeometryKind.PRIMITIVE
        if self.source_path:
            suffix = Path(self.source_path).suffix.lower()
            if suffix in {".stl", ".obj", ".ply", ".off", ".3mf", ".glb", ".gltf"}:
                return GeometryKind.MESH
        return GeometryKind.BREP

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role.value,
            "transform": self.transform.to_dict(),
            "source_path": self.source_path,
            "primitive": self.primitive.to_dict() if self.primitive else None,
            "visible": bool(self.visible),
            "included_in_envelope_fit": bool(self.included_in_envelope_fit),
            "clearance_mode": self.clearance_mode.value,
            "clearance_mm": float(self.clearance_mm),
            "color": list(self.color) if self.color is not None else None,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SceneObject":
        color = value.get("color")
        return cls(
            id=str(value.get("id") or uuid4()),
            name=str(value.get("name", "Object")),
            role=ObjectRole(value.get("role", ObjectRole.OCCUPANT.value)),
            transform=Transform.from_dict(value.get("transform")),
            source_path=value.get("source_path"),
            primitive=(
                PrimitiveSpec.from_dict(value["primitive"])
                if value.get("primitive")
                else None
            ),
            visible=bool(value.get("visible", True)),
            included_in_envelope_fit=bool(value.get("included_in_envelope_fit", True)),
            clearance_mode=ClearanceMode(
                value.get("clearance_mode", ClearanceMode.AABB.value)
            ),
            clearance_mm=float(value.get("clearance_mm", 0.5)),
            color=(tuple(float(v) for v in color) if color is not None else None),
            metadata=dict(value.get("metadata") or {}),
        )


@dataclass(slots=True)
class EnvelopeSpec:
    kind: PrimitiveKind = PrimitiveKind.ROUNDED_BOX
    size: Vector3 = field(default_factory=lambda: Vector3(100.0, 70.0, 25.0))
    transform: Transform = field(default_factory=Transform)
    radius: float = 6.0
    fit_margin: Vector3 = field(default_factory=lambda: Vector3(3.0, 3.0, 3.0))

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "size": self.size.to_list(),
            "transform": self.transform.to_dict(),
            "radius": float(self.radius),
            "fit_margin": self.fit_margin.to_list(),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "EnvelopeSpec":
        value = value or {}
        return cls(
            kind=PrimitiveKind(
                value.get("kind", PrimitiveKind.ROUNDED_BOX.value)
            ),
            size=Vector3.from_value(value.get("size"), Vector3(100.0, 70.0, 25.0)),
            transform=Transform.from_dict(value.get("transform")),
            radius=float(value.get("radius", 6.0)),
            fit_margin=Vector3.from_value(
                value.get("fit_margin"), Vector3(3.0, 3.0, 3.0)
            ),
        )


@dataclass(slots=True)
class SplitSpec:
    enabled: bool = False
    axis: SplitAxis = SplitAxis.Z
    offset: float = 0.0
    gap: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": bool(self.enabled),
            "axis": self.axis.value,
            "offset": float(self.offset),
            "gap": float(self.gap),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "SplitSpec":
        value = value or {}
        return cls(
            enabled=bool(value.get("enabled", False)),
            axis=SplitAxis(value.get("axis", SplitAxis.Z.value)),
            offset=float(value.get("offset", 0.0)),
            gap=float(value.get("gap", 0.0)),
        )


@dataclass(slots=True)
class Project:
    schema_version: int = 1
    name: str = "Untitled FlipFill Project"
    units: str = "mm"
    objects: list[SceneObject] = field(default_factory=list)
    envelope: EnvelopeSpec = field(default_factory=EnvelopeSpec)
    split: SplitSpec = field(default_factory=SplitSpec)
    boolean_tolerance: float = 1.0e-4
    tessellation_tolerance: float = 0.15
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": int(self.schema_version),
            "name": self.name,
            "units": self.units,
            "objects": [obj.to_dict() for obj in self.objects],
            "envelope": self.envelope.to_dict(),
            "split": self.split.to_dict(),
            "boolean_tolerance": float(self.boolean_tolerance),
            "tessellation_tolerance": float(self.tessellation_tolerance),
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Project":
        schema_version = int(value.get("schema_version", 1))
        if schema_version != 1:
            raise ValueError(
                f"Unsupported project schema {schema_version}; this build supports schema 1"
            )
        return cls(
            schema_version=schema_version,
            name=str(value.get("name", "Untitled FlipFill Project")),
            units=str(value.get("units", "mm")),
            objects=[SceneObject.from_dict(v) for v in value.get("objects", [])],
            envelope=EnvelopeSpec.from_dict(value.get("envelope")),
            split=SplitSpec.from_dict(value.get("split")),
            boolean_tolerance=float(value.get("boolean_tolerance", 1.0e-4)),
            tessellation_tolerance=float(value.get("tessellation_tolerance", 0.15)),
            notes=str(value.get("notes", "")),
        )

    def object_by_id(self, object_id: str) -> SceneObject | None:
        return next((obj for obj in self.objects if obj.id == object_id), None)

    def remove_objects(self, object_ids: Iterable[str]) -> None:
        ids = set(object_ids)
        self.objects[:] = [obj for obj in self.objects if obj.id not in ids]
