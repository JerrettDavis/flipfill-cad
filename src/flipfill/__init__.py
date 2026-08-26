"""FlipFill CAD: clearance-first inverse-fill enclosure generation."""

from .model import (
    ClearanceMode,
    EnvelopeSpec,
    ObjectRole,
    PrimitiveKind,
    Project,
    SceneObject,
    SliceCutterKind,
    SliceSpec,
    Transform,
    Vector3,
)

__all__ = [
    "ClearanceMode",
    "EnvelopeSpec",
    "ObjectRole",
    "PrimitiveKind",
    "Project",
    "SceneObject",
    "SliceCutterKind",
    "SliceSpec",
    "Transform",
    "Vector3",
]

__version__ = "0.1.0"
