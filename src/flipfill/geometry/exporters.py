from __future__ import annotations

from pathlib import Path

import cadquery as cq
from cadquery import exporters

from flipfill.geometry.generator import GenerationResult
from flipfill.model import ObjectRole, Project


class ExportError(RuntimeError):
    pass


def export_shape(shape: cq.Shape, path: str | Path) -> Path:
    output = Path(path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    suffix = output.suffix.lower()
    try:
        if suffix in {".step", ".stp"}:
            exporters.export(shape, str(output), exportType="STEP")
        elif suffix == ".stl":
            exporters.export(
                shape,
                str(output),
                exportType="STL",
                tolerance=0.05,
                angularTolerance=0.1,
            )
        elif suffix in {".brep", ".brp"}:
            shape.exportBrep(str(output))
        else:
            raise ExportError(
                f"Unsupported export extension '{suffix}'. Use STEP, STL, or BREP."
            )
    except ExportError:
        raise
    except Exception as exc:
        raise ExportError(f"Could not export {output}: {exc}") from exc
    return output


def export_fitcheck_assembly(
    project: Project,
    generated: GenerationResult,
    path: str | Path,
) -> Path:
    output = Path(path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.suffix.lower() not in {".step", ".stp"}:
        raise ExportError("Fit-check assemblies must be exported as STEP")

    assembly = cq.Assembly(name=project.name)
    assembly.add(
        generated.result,
        name="GENERATED_BODY",
        color=cq.Color(0.75, 0.78, 0.82, 0.82),
    )

    colors = {
        ObjectRole.OCCUPANT: cq.Color(0.95, 0.55, 0.10, 0.55),
        ObjectRole.CUTOUT: cq.Color(0.90, 0.15, 0.15, 0.45),
        ObjectRole.ADDITIVE: cq.Color(0.15, 0.65, 0.30, 0.55),
        ObjectRole.REFERENCE: cq.Color(0.20, 0.45, 0.90, 0.40),
    }
    for index, generated_object in enumerate(generated.objects):
        if generated_object.resolved.brep is None:
            continue
        role = generated_object.scene_object.role
        assembly.add(
            generated_object.resolved.brep,
            name=f"{role.value.upper()}_{index:02d}_{generated_object.scene_object.name}",
            color=colors.get(role, cq.Color(0.5, 0.5, 0.5, 0.4)),
        )

    try:
        assembly.export(str(output), mode="default")
    except Exception as exc:
        raise ExportError(f"Could not export fit-check assembly: {exc}") from exc
    return output
