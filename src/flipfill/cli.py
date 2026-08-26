"""FlipFill CAD command-line interface.

The CLI is the primary way to drive FlipFill: every scene edit the desktop
GUI can make (import, position, classify, add blockers, fit an envelope,
generate, validate, slice, export, render) has a scripted equivalent here,
backed by the same :mod:`flipfill.commands` service layer and
:mod:`flipfill.geometry` pipeline the GUI uses. Nothing here re-implements
geometry logic.

Mutating commands (``new``, ``import``, ``move``, ``rotate``, ``align``,
``role``, ``clearance``, ``blocker``, ``envelope``, ``slice``) load a
project, apply one change, and save it back to disk — so they compose in
shell scripts:

    flipfill import proj.flipfill.json battery.step --role occupant
    flipfill move proj.flipfill.json Battery --x 12 --y 0 --z 4
    flipfill envelope proj.flipfill.json --fit
    flipfill generate proj.flipfill.json -o out/case.step --fitcheck out/fitcheck.step

Every command accepts ``--json`` where structured output is useful, and
returns a nonzero exit code on failure so it is safe to use in CI.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, NoReturn

from flipfill import commands
from flipfill.commands import CommandError
from flipfill.geometry.exporters import (
    ExportError,
    export_fitcheck_assembly,
    export_shape,
)
from flipfill.geometry.generator import GenerationError, MessageLevel, generate
from flipfill.geometry.importers import GeometryRepository, ImportGeometryError
from flipfill.model import (
    ClearanceMode,
    ObjectRole,
    PrimitiveKind,
    SliceCutterKind,
    Transform,
    Vector3,
)
from flipfill.project_io import ProjectIoError, load_project, save_project

try:
    from importlib.metadata import version as _pkg_version

    __version__ = _pkg_version("flipfill-cad")
except Exception:  # pragma: no cover - only when running from an uninstalled checkout
    __version__ = "0.0.0-dev"


class CliError(RuntimeError):
    """Raised to abort a command with a clean, single-line message."""


# ----------------------------------------------------------------------
# Small output helpers
# ----------------------------------------------------------------------


def _emit(args: argparse.Namespace, data: dict[str, Any], text: str) -> None:
    if getattr(args, "json", False):
        print(json.dumps(data, indent=2))
    else:
        print(text)


def _die(message: str) -> NoReturn:
    raise CliError(message)


def _print_messages(messages) -> None:
    for message in messages:
        prefix = message.level.value.upper()
        object_suffix = f" [{message.object_id}]" if message.object_id else ""
        print(f"{prefix}{object_suffix}: {message.message}")


def _load(path: str) -> Any:
    try:
        return load_project(path)
    except ProjectIoError as exc:
        _die(str(exc))


def _save(project, path: str) -> None:
    try:
        save_project(project, path)
    except ProjectIoError as exc:
        _die(str(exc))


def _vector_arg(namespace: argparse.Namespace, prefix: str) -> Vector3 | None:
    x = getattr(namespace, f"{prefix}_x", None)
    y = getattr(namespace, f"{prefix}_y", None)
    z = getattr(namespace, f"{prefix}_z", None)
    if x is None and y is None and z is None:
        return None
    if x is None or y is None or z is None:
        _die(f"--{prefix}-x, --{prefix}-y, and --{prefix}-z must be given together")
    return Vector3(x, y, z)


def _slugify(name: str) -> str:
    slug = "".join(c.lower() if c.isalnum() else "_" for c in name).strip("_")
    return slug or "body"


# ----------------------------------------------------------------------
# new
# ----------------------------------------------------------------------


def command_new(args: argparse.Namespace) -> int:
    project_path = Path(args.project)
    if project_path.exists() and not args.force:
        _die(f"{project_path} already exists; pass --force to overwrite")
    if args.force and project_path.exists():
        project_path.unlink()
    try:
        path = commands.create_project(args.project, name=args.name, units=args.units)
    except CommandError as exc:
        _die(str(exc))
    _emit(
        args,
        {"ok": True, "path": str(path)},
        f"Created project {path}",
    )
    return 0


# ----------------------------------------------------------------------
# import
# ----------------------------------------------------------------------


def command_import(args: argparse.Namespace) -> int:
    project = _load(args.project)
    repository = GeometryRepository()
    try:
        added = commands.import_geometry(
            project,
            repository,
            args.source,
            role=ObjectRole(args.role),
            name=args.name,
            clearance_mode=ClearanceMode(args.clearance_mode),
            clearance_mm=args.clearance,
        )
    except CommandError as exc:
        _die(str(exc))
    _save(project, args.project)
    _emit(
        args,
        {"ok": True, "added": [commands.summarize_object(o) for o in added]},
        f"Imported {len(added)} object(s) into {args.project}:\n"
        + "\n".join(f"  {o.id}  {o.name}  ({o.role.value})" for o in added),
    )
    return 0


# ----------------------------------------------------------------------
# list
# ----------------------------------------------------------------------


def command_list(args: argparse.Namespace) -> int:
    project = _load(args.project)
    rows = commands.list_objects(project)
    if getattr(args, "json", False):
        print(json.dumps({"objects": rows}, indent=2))
        return 0
    if not rows:
        print("No objects. Use 'flipfill import' or 'flipfill blocker' to add one.")
        return 0
    name_width = max(4, max(len(r["name"]) for r in rows))
    print(f"{'ID':<36}  {'NAME':<{name_width}}  {'ROLE':<9}  {'KIND':<9}  VISIBLE")
    for row in rows:
        print(
            f"{row['id']:<36}  {row['name']:<{name_width}}  {row['role']:<9}  "
            f"{row['kind']:<9}  {'yes' if row['visible'] else 'no'}"
        )
    return 0


# ----------------------------------------------------------------------
# inspect
# ----------------------------------------------------------------------


def command_inspect(args: argparse.Namespace) -> int:
    project = _load(args.project)
    repository = GeometryRepository()
    try:
        result = commands.inspect_object(project, repository, args.object)
    except CommandError as exc:
        _die(str(exc))
    if getattr(args, "json", False):
        print(json.dumps(result.to_dict(), indent=2))
        return 0
    summary = result.summary
    print(f"{summary['name']}  ({summary['id']})")
    print(f"  role: {summary['role']}   kind: {summary['kind']}")
    if summary["source_path"]:
        print(f"  source: {summary['source_path']}")
    print(f"  translation: {summary['translation']}   rotation_deg: {summary['rotation_deg']}")
    print(f"  clearance: {summary['clearance_mode']} / {summary['clearance_mm']} mm")
    print(f"  visible: {summary['visible']}   included_in_envelope_fit: {summary['included_in_envelope_fit']}")
    if result.bounds is not None:
        b = result.bounds
        print(f"  bounds: min={b.minimum.to_list()} max={b.maximum.to_list()} size={b.size.to_list()}")
    if result.error:
        print(f"  WARNING: could not resolve geometry: {result.error}")
    return 0


# ----------------------------------------------------------------------
# move / rotate
# ----------------------------------------------------------------------


def command_move(args: argparse.Namespace) -> int:
    project = _load(args.project)
    try:
        scene_object = commands.find_object(project, args.object)
        commands.move_object(scene_object, args.x, args.y, args.z, relative=args.relative)
    except CommandError as exc:
        _die(str(exc))
    _save(project, args.project)
    _emit(
        args,
        {"ok": True, "object": commands.summarize_object(scene_object)},
        f"{scene_object.name}: translation now {scene_object.transform.translation.to_list()}",
    )
    return 0


def command_rotate(args: argparse.Namespace) -> int:
    project = _load(args.project)
    try:
        scene_object = commands.find_object(project, args.object)
        commands.rotate_object(scene_object, args.x, args.y, args.z, relative=args.relative)
    except CommandError as exc:
        _die(str(exc))
    _save(project, args.project)
    _emit(
        args,
        {"ok": True, "object": commands.summarize_object(scene_object)},
        f"{scene_object.name}: rotation now {scene_object.transform.rotation_deg.to_list()}",
    )
    return 0


# ----------------------------------------------------------------------
# align
# ----------------------------------------------------------------------


def command_align(args: argparse.Namespace) -> int:
    project = _load(args.project)
    repository = GeometryRepository()
    try:
        scene_object = commands.find_object(project, args.object)
        commands.align_object(
            project, repository, scene_object, args.axis, args.mode, target_ref=args.to
        )
    except (CommandError, ImportGeometryError) as exc:
        _die(str(exc))
    _save(project, args.project)
    target_desc = f"to {args.to}" if args.to else "to the origin"
    _emit(
        args,
        {"ok": True, "object": commands.summarize_object(scene_object)},
        f"{scene_object.name}: aligned {args.mode} of {args.axis.upper()} {target_desc}; "
        f"translation now {scene_object.transform.translation.to_list()}",
    )
    return 0


# ----------------------------------------------------------------------
# role / clearance
# ----------------------------------------------------------------------


def command_role(args: argparse.Namespace) -> int:
    project = _load(args.project)
    try:
        scene_object = commands.find_object(project, args.object)
        commands.set_role(scene_object, ObjectRole(args.role))
    except CommandError as exc:
        _die(str(exc))
    _save(project, args.project)
    _emit(
        args,
        {"ok": True, "object": commands.summarize_object(scene_object)},
        f"{scene_object.name}: role set to {scene_object.role.value}",
    )
    return 0


def command_clearance(args: argparse.Namespace) -> int:
    project = _load(args.project)
    try:
        scene_object = commands.find_object(project, args.object)
        commands.set_clearance(
            scene_object,
            ClearanceMode(args.mode) if args.mode else None,
            args.mm,
        )
    except CommandError as exc:
        _die(str(exc))
    _save(project, args.project)
    _emit(
        args,
        {"ok": True, "object": commands.summarize_object(scene_object)},
        f"{scene_object.name}: clearance is now {scene_object.clearance_mode.value} / "
        f"{scene_object.clearance_mm} mm",
    )
    return 0


# ----------------------------------------------------------------------
# blocker
# ----------------------------------------------------------------------


def command_blocker(args: argparse.Namespace) -> int:
    project = _load(args.project)
    translation = _vector_arg(args, "at") or Vector3()
    rotation = _vector_arg(args, "rotate") or Vector3()
    size = Vector3(*args.size)
    try:
        scene_object = commands.add_primitive_object(
            project,
            role=ObjectRole(args.role),
            kind=PrimitiveKind(args.kind),
            size=size,
            radius=args.radius,
            translation=translation,
            rotation_deg=rotation,
            name=args.name,
            clearance_mode=ClearanceMode(args.clearance_mode) if args.clearance_mode else None,
            clearance_mm=args.clearance,
        )
    except Exception as exc:  # primitive validation errors
        _die(str(exc))
    _save(project, args.project)
    _emit(
        args,
        {"ok": True, "object": commands.summarize_object(scene_object)},
        f"Added {scene_object.role.value} '{scene_object.name}' ({scene_object.id}) "
        f"as a {args.kind} primitive",
    )
    return 0


# ----------------------------------------------------------------------
# envelope
# ----------------------------------------------------------------------


def command_envelope(args: argparse.Namespace) -> int:
    project = _load(args.project)
    repository = GeometryRepository()
    try:
        commands.configure_envelope(
            project,
            kind=PrimitiveKind(args.kind) if args.kind else None,
            size=Vector3(*args.size) if args.size else None,
            translation=_vector_arg(args, "center"),
            rotation_deg=_vector_arg(args, "rotation"),
            radius=args.radius,
            fit_margin=Vector3(*args.margin) if args.margin else None,
        )
        if args.fit or args.fit_selection:
            object_ids = None
            if args.fit_selection:
                object_ids = [commands.find_object(project, ref).id for ref in args.fit_selection]
            fitted = commands.fit_envelope(project, repository, object_ids)
        else:
            fitted = None
    except (CommandError, GenerationError, ImportGeometryError) as exc:
        _die(str(exc))
    _save(project, args.project)
    envelope = project.envelope
    detail = (
        f"Envelope: {envelope.kind.value} size={envelope.size.to_list()} "
        f"center={envelope.transform.translation.to_list()} radius={envelope.radius}"
    )
    if fitted is not None:
        detail += f"\nFitted to size={fitted.size.to_list()} center={fitted.center.to_list()}"
    _emit(
        args,
        {"ok": True, "envelope": envelope.to_dict()},
        detail,
    )
    return 0


# ----------------------------------------------------------------------
# slice
# ----------------------------------------------------------------------


def _slice_to_dict(project, slice_spec) -> dict[str, Any]:
    data = slice_spec.to_dict()
    if slice_spec.object_id:
        target = project.object_by_id(slice_spec.object_id)
        data["object_name"] = target.name if target else None
    return data


def command_slice_add(args: argparse.Namespace) -> int:
    project = _load(args.project)
    cutter_kind = SliceCutterKind.OBJECT if args.object_ref else SliceCutterKind.PLANE
    transform = None
    if cutter_kind is SliceCutterKind.PLANE:
        transform = Transform(
            translation=Vector3(args.at_x, args.at_y, args.at_z),
            rotation_deg=Vector3(args.rotate_x, args.rotate_y, args.rotate_z),
        )
    try:
        slice_spec = commands.add_slice(
            project,
            name=args.name,
            cutter_kind=cutter_kind,
            transform=transform,
            gap=args.gap,
            object_id=args.object_ref,
            index=args.index,
        )
    except CommandError as exc:
        _die(str(exc))
    _save(project, args.project)
    _emit(
        args,
        {"ok": True, "slice": _slice_to_dict(project, slice_spec)},
        f"Added slice '{slice_spec.name}' ({slice_spec.cutter_kind.value})",
    )
    return 0


def command_slice_remove(args: argparse.Namespace) -> int:
    project = _load(args.project)
    try:
        commands.remove_slice(project, args.slice)
    except CommandError as exc:
        _die(str(exc))
    _save(project, args.project)
    _emit(args, {"ok": True}, f"Removed slice {args.slice!r}")
    return 0


def command_slice_move(args: argparse.Namespace) -> int:
    project = _load(args.project)
    try:
        commands.reorder_slice(project, args.slice, args.to_index)
    except CommandError as exc:
        _die(str(exc))
    _save(project, args.project)
    _emit(args, {"ok": True}, f"Moved slice {args.slice!r} to index {args.to_index}")
    return 0


def command_slice_list(args: argparse.Namespace) -> int:
    project = _load(args.project)
    slices = commands.list_slices(project)
    payload = [_slice_to_dict(project, s) for s in slices]
    lines = [f"{i}: {s.name} ({s.cutter_kind.value})" for i, s in enumerate(slices)] or [
        "(no slices configured)"
    ]
    _emit(args, {"ok": True, "slices": payload}, "\n".join(lines))
    return 0


def command_slice_enable(args: argparse.Namespace) -> int:
    project = _load(args.project)
    commands.configure_slicing(project, enabled=args.enabled)
    _save(project, args.project)
    _emit(
        args,
        {"ok": True, "enabled": project.slicing.enabled},
        f"Slicing {'enabled' if args.enabled else 'disabled'}",
    )
    return 0


def command_slice_remainder_name(args: argparse.Namespace) -> int:
    project = _load(args.project)
    try:
        commands.configure_slicing(project, remainder_name=args.name)
    except CommandError as exc:
        _die(str(exc))
    _save(project, args.project)
    _emit(
        args,
        {"ok": True, "remainder_name": project.slicing.remainder_name},
        f"Remainder name set to {args.name!r}",
    )
    return 0


# ----------------------------------------------------------------------
# generate / validate (existing, kept and extended with --json)
# ----------------------------------------------------------------------


def command_generate(args: argparse.Namespace) -> int:
    project = _load(args.project)
    repository = GeometryRepository()
    try:
        generated = generate(project, repository)
    except GenerationError as exc:
        _die(str(exc))

    if not getattr(args, "json", False):
        _print_messages(generated.messages)

    errors = [m for m in generated.messages if m.level is MessageLevel.ERROR]
    if errors and not args.force:
        if getattr(args, "json", False):
            print(
                json.dumps(
                    {
                        "ok": False,
                        "errors": [m.message for m in errors],
                        "messages": [m.message for m in generated.messages],
                    },
                    indent=2,
                )
            )
        else:
            print(
                "Generation contains validation errors; use --force to export anyway.",
                file=sys.stderr,
            )
        return 2

    output = export_shape(generated.result, args.output)
    outputs = {"body": str(output)}
    if not getattr(args, "json", False):
        print(f"Exported generated body: {output}")

    if args.fitcheck:
        assembly = export_fitcheck_assembly(project, generated, args.fitcheck)
        outputs["fitcheck"] = str(assembly)
        if not getattr(args, "json", False):
            print(f"Exported fit-check assembly: {assembly}")

    if project.slicing.enabled and generated.sliced_bodies:
        slice_dir = Path(args.slice_dir or Path(args.output).parent).resolve()
        slice_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(args.output).stem
        slice_outputs: dict[str, str] = {}
        for name, shape in generated.sliced_bodies.items():
            exported = export_shape(shape, slice_dir / f"{stem}_{_slugify(name)}.step")
            slice_outputs[name] = str(exported)
        outputs["slices"] = slice_outputs
        if not getattr(args, "json", False):
            print("Exported sliced bodies: " + ", ".join(slice_outputs.values()))

    if getattr(args, "json", False):
        print(
            json.dumps(
                {
                    "ok": True,
                    "outputs": outputs,
                    "volume_mm3": generated.result.Volume(),
                    "messages": [m.message for m in generated.messages],
                },
                indent=2,
            )
        )
    return 0


def command_validate(args: argparse.Namespace) -> int:
    project = _load(args.project)
    try:
        generated = generate(project, GeometryRepository())
    except GenerationError as exc:
        _die(str(exc))
    errors = [m for m in generated.messages if m.level is MessageLevel.ERROR]

    if getattr(args, "json", False):
        print(
            json.dumps(
                {
                    "ok": not errors,
                    "valid": generated.result.isValid(),
                    "volume_mm3": generated.result.Volume(),
                    "warnings": [m.message for m in generated.warnings],
                    "errors": [m.message for m in errors],
                },
                indent=2,
            )
        )
        return 1 if errors else 0

    _print_messages(generated.messages)
    print(
        f"Result valid={generated.result.isValid()} "
        f"volume={generated.result.Volume():.3f} mm³ "
        f"warnings={len(generated.warnings)} errors={len(errors)}"
    )
    return 1 if errors else 0


# ----------------------------------------------------------------------
# export
# ----------------------------------------------------------------------


def command_export(args: argparse.Namespace) -> int:
    project = _load(args.project)
    repository = GeometryRepository()
    try:
        generated = generate(project, repository)
    except GenerationError as exc:
        _die(str(exc))

    errors = [m for m in generated.messages if m.level is MessageLevel.ERROR]
    if errors and not args.force:
        print("Generation contains validation errors; use --force to export anyway.", file=sys.stderr)
        for message in errors:
            print(f"ERROR: {message.message}", file=sys.stderr)
        return 2

    try:
        if args.target == "package":
            output_dir = Path(args.output).expanduser().resolve()
            output_dir.mkdir(parents=True, exist_ok=True)
            stem = "".join(
                c if c.isalnum() or c in "-_" else "_" for c in project.name
            ).strip("_") or "flipfill"
            written = {
                "step": str(export_shape(generated.result, output_dir / f"{stem}.step")),
                "stl": str(export_shape(generated.result, output_dir / f"{stem}.stl")),
                "fitcheck": str(
                    export_fitcheck_assembly(
                        project, generated, output_dir / f"{stem}_fitcheck.step"
                    )
                ),
            }
            for name, shape in generated.sliced_bodies.items():
                written[f"slice:{name}"] = str(
                    export_shape(shape, output_dir / f"{stem}_{_slugify(name)}.step")
                )
            save_project(project, output_dir / f"{stem}.flipfill.json")
            written["project"] = str(output_dir / f"{stem}.flipfill.json")
        elif args.target == "fitcheck":
            written = {"fitcheck": str(export_fitcheck_assembly(project, generated, args.output))}
        elif args.target == "stl":
            written = {"stl": str(export_shape(generated.result, args.output))}
        else:
            written = {"step": str(export_shape(generated.result, args.output))}
    except ExportError as exc:
        _die(str(exc))

    _emit(
        args,
        {"ok": True, "outputs": written},
        "\n".join(f"Exported {key}: {value}" for key, value in written.items()),
    )
    return 0


# ----------------------------------------------------------------------
# render
# ----------------------------------------------------------------------


def command_render(args: argparse.Namespace) -> int:
    project = _load(args.project)
    repository = GeometryRepository()

    generated = None
    if args.generate:
        try:
            generated = generate(project, repository)
        except GenerationError as exc:
            _die(str(exc))

    from flipfill.rendering import render_project_to_file

    path, errors = render_project_to_file(
        project,
        repository,
        args.output,
        generated=generated,
        view=args.view,
        show_envelope=not args.no_envelope,
        width=args.width,
        height=args.height,
    )
    for error in errors:
        print(f"WARNING: {error}", file=sys.stderr)
    _emit(
        args,
        {"ok": True, "path": str(path), "warnings": errors},
        f"Rendered {path}",
    )
    return 0


# ----------------------------------------------------------------------
# doctor
# ----------------------------------------------------------------------


def command_doctor(args: argparse.Namespace) -> int:
    report = commands.run_doctor()
    if getattr(args, "json", False):
        print(json.dumps(report.to_dict(), indent=2))
        return 0 if report.ok else 1
    for check in report.checks:
        status = "OK  " if check.ok else "FAIL"
        print(f"[{status}] {check.name}: {check.detail}")
    print()
    print("All checks passed." if report.ok else "Some checks failed; see above.")
    return 0 if report.ok else 1


# ----------------------------------------------------------------------
# gui
# ----------------------------------------------------------------------


def command_gui(args: argparse.Namespace) -> int:
    from flipfill.ui.app import run_app

    return run_app(args.project)


# ----------------------------------------------------------------------
# Parser
# ----------------------------------------------------------------------

_EPILOG = """\
examples:
  flipfill new my_case.flipfill.json --name "Handheld Case"
  flipfill import my_case.flipfill.json battery.step --role occupant --clearance 0.5
  flipfill move my_case.flipfill.json Battery --x 0 --y 0 --z 4
  flipfill blocker my_case.flipfill.json --role cutout --kind box --size 10 6 6 --at-x 20 --at-y 0 --at-z 0
  flipfill envelope my_case.flipfill.json --fit --margin 3 3 3
  flipfill generate my_case.flipfill.json -o out/case.step --fitcheck out/case_fitcheck.step
  flipfill validate my_case.flipfill.json --json
  flipfill render my_case.flipfill.json out/preview.png --view iso
  flipfill doctor

Run 'flipfill <command> --help' for a command's full options.
"""


def _add_json_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON instead of text")


def _add_object_transform_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--x", type=float, required=True, help="X value (mm or degrees)")
    parser.add_argument("--y", type=float, required=True, help="Y value (mm or degrees)")
    parser.add_argument("--z", type=float, required=True, help="Z value (mm or degrees)")
    parser.add_argument(
        "--relative", action="store_true", help="Add to the current value instead of replacing it"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flipfill",
        description=(
            "FlipFill CAD: clearance-first enclosure generation from positioned CAD objects.\n\n"
            "result = (envelope ∪ additives) − occupant-clearances − cutout-blockers"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_EPILOG,
    )
    parser.add_argument("--version", action="version", version=f"flipfill {__version__}")
    subparsers = parser.add_subparsers(dest="command")

    # gui
    gui = subparsers.add_parser("gui", help="Launch the desktop application")
    gui.add_argument("project", nargs="?", help="Optional .flipfill.json project")
    gui.set_defaults(handler=command_gui)

    # new
    new = subparsers.add_parser("new", help="Create a new, empty project")
    new.add_argument("project", help="Path to the .flipfill.json project to create")
    new.add_argument("--name", help="Project display name (default: file stem)")
    new.add_argument("--units", default="mm", help="Project units (default: mm)")
    new.add_argument("--force", action="store_true", help="Overwrite an existing file")
    _add_json_flag(new)
    new.set_defaults(handler=command_new)

    # import
    imp = subparsers.add_parser("import", help="Import STEP/STP/BREP/IGES or a mesh reference")
    imp.add_argument("project")
    imp.add_argument("source", nargs="+", help="One or more geometry files to import")
    imp.add_argument(
        "--role",
        default=ObjectRole.OCCUPANT.value,
        choices=[r.value for r in ObjectRole if r is not ObjectRole.RESULT],
    )
    imp.add_argument("--name", help="Object name (single-file imports only; default: file stem)")
    imp.add_argument(
        "--clearance-mode",
        default=ClearanceMode.AABB.value,
        choices=[m.value for m in ClearanceMode],
    )
    imp.add_argument("--clearance", type=float, default=0.5, help="Clearance in mm (default: 0.5)")
    _add_json_flag(imp)
    imp.set_defaults(handler=command_import)

    # list
    ls = subparsers.add_parser("list", help="List scene objects")
    ls.add_argument("project")
    _add_json_flag(ls)
    ls.set_defaults(handler=command_list)

    # inspect
    inspect = subparsers.add_parser("inspect", help="Show full detail for one scene object")
    inspect.add_argument("project")
    inspect.add_argument("object", help="Object id or name")
    _add_json_flag(inspect)
    inspect.set_defaults(handler=command_inspect)

    # move
    move = subparsers.add_parser("move", help="Set or offset an object's position")
    move.add_argument("project")
    move.add_argument("object", help="Object id or name")
    _add_object_transform_flags(move)
    _add_json_flag(move)
    move.set_defaults(handler=command_move)

    # rotate
    rotate = subparsers.add_parser("rotate", help="Set or offset an object's rotation (degrees)")
    rotate.add_argument("project")
    rotate.add_argument("object", help="Object id or name")
    _add_object_transform_flags(rotate)
    _add_json_flag(rotate)
    rotate.set_defaults(handler=command_rotate)

    # align
    align = subparsers.add_parser(
        "align", help="Align one axis of an object's bounds to another object or the origin"
    )
    align.add_argument("project")
    align.add_argument("object", help="Object id or name to move")
    align.add_argument("--axis", required=True, choices=["x", "y", "z"])
    align.add_argument("--mode", required=True, choices=["min", "max", "center"])
    align.add_argument("--to", help="Object id or name to align against (default: origin)")
    _add_json_flag(align)
    align.set_defaults(handler=command_align)

    # role
    role = subparsers.add_parser("role", help="Set an object's scene role")
    role.add_argument("project")
    role.add_argument("object", help="Object id or name")
    role.add_argument("role", choices=[r.value for r in ObjectRole if r is not ObjectRole.RESULT])
    _add_json_flag(role)
    role.set_defaults(handler=command_role)

    # clearance
    clearance = subparsers.add_parser("clearance", help="Set an object's clearance mode/amount")
    clearance.add_argument("project")
    clearance.add_argument("object", help="Object id or name")
    clearance.add_argument("--mode", choices=[m.value for m in ClearanceMode])
    clearance.add_argument("--mm", type=float, dest="mm", help="Clearance amount in mm")
    _add_json_flag(clearance)
    clearance.set_defaults(handler=command_clearance)

    # blocker
    blocker = subparsers.add_parser(
        "blocker", help="Add a primitive occupant, cutout blocker, or additive"
    )
    blocker.add_argument("project")
    blocker.add_argument(
        "--role",
        default=ObjectRole.CUTOUT.value,
        choices=[ObjectRole.OCCUPANT.value, ObjectRole.CUTOUT.value, ObjectRole.ADDITIVE.value],
    )
    blocker.add_argument("--kind", default=PrimitiveKind.BOX.value, choices=[k.value for k in PrimitiveKind])
    blocker.add_argument("--name", help="Object name (default: role name)")
    blocker.add_argument("--size", type=float, nargs=3, metavar=("X", "Y", "Z"), required=True)
    blocker.add_argument("--radius", type=float, default=0.0, help="Corner/fillet radius (mm)")
    blocker.add_argument("--at-x", type=float, dest="at_x", default=0.0)
    blocker.add_argument("--at-y", type=float, dest="at_y", default=0.0)
    blocker.add_argument("--at-z", type=float, dest="at_z", default=0.0)
    blocker.add_argument("--rotate-x", type=float, dest="rotate_x", default=0.0)
    blocker.add_argument("--rotate-y", type=float, dest="rotate_y", default=0.0)
    blocker.add_argument("--rotate-z", type=float, dest="rotate_z", default=0.0)
    blocker.add_argument("--clearance-mode", choices=[m.value for m in ClearanceMode])
    blocker.add_argument("--clearance", type=float, dest="clearance")
    _add_json_flag(blocker)
    blocker.set_defaults(handler=command_blocker)

    # envelope
    envelope = subparsers.add_parser("envelope", help="Configure or auto-fit the envelope")
    envelope.add_argument("project")
    envelope.add_argument("--kind", choices=[PrimitiveKind.BOX.value, PrimitiveKind.ROUNDED_BOX.value])
    envelope.add_argument("--size", type=float, nargs=3, metavar=("X", "Y", "Z"))
    envelope.add_argument("--center-x", type=float, dest="center_x")
    envelope.add_argument("--center-y", type=float, dest="center_y")
    envelope.add_argument("--center-z", type=float, dest="center_z")
    envelope.add_argument("--rotation-x", type=float, dest="rotation_x")
    envelope.add_argument("--rotation-y", type=float, dest="rotation_y")
    envelope.add_argument("--rotation-z", type=float, dest="rotation_z")
    envelope.add_argument("--radius", type=float)
    envelope.add_argument("--margin", type=float, nargs=3, metavar=("X", "Y", "Z"))
    envelope.add_argument("--fit", action="store_true", help="Auto-fit to all included objects")
    envelope.add_argument(
        "--fit-selection",
        nargs="+",
        metavar="OBJECT",
        help="Auto-fit to only these object ids/names",
    )
    _add_json_flag(envelope)
    envelope.set_defaults(handler=command_envelope)

    # slice
    slice_parser = subparsers.add_parser("slice", help="Manage the ordered slice/cut list")
    slice_parser.add_argument("project")
    slice_sub = slice_parser.add_subparsers(dest="slice_command", required=True)

    slice_add = slice_sub.add_parser("add", help="Add a plane or object cutter slice")
    slice_add.add_argument("--name", required=True)
    cutter_group = slice_add.add_mutually_exclusive_group(required=True)
    cutter_group.add_argument("--plane", action="store_true")
    cutter_group.add_argument(
        "--object", dest="object_ref", help="Object id or name to use as the cutting solid"
    )
    slice_add.add_argument("--at-x", type=float, dest="at_x", default=0.0)
    slice_add.add_argument("--at-y", type=float, dest="at_y", default=0.0)
    slice_add.add_argument("--at-z", type=float, dest="at_z", default=0.0)
    slice_add.add_argument("--rotate-x", type=float, dest="rotate_x", default=0.0)
    slice_add.add_argument("--rotate-y", type=float, dest="rotate_y", default=0.0)
    slice_add.add_argument("--rotate-z", type=float, dest="rotate_z", default=0.0)
    slice_add.add_argument("--gap", type=float, default=0.0)
    slice_add.add_argument("--index", type=int, help="Insert position (default: append)")
    _add_json_flag(slice_add)
    slice_add.set_defaults(handler=command_slice_add)

    slice_remove = slice_sub.add_parser("remove", help="Remove a slice by name or index")
    slice_remove.add_argument("slice", help="Slice name or index")
    _add_json_flag(slice_remove)
    slice_remove.set_defaults(handler=command_slice_remove)

    slice_move = slice_sub.add_parser("move", help="Reorder a slice")
    slice_move.add_argument("slice", help="Slice name or index")
    slice_move.add_argument("--to", type=int, required=True, dest="to_index")
    _add_json_flag(slice_move)
    slice_move.set_defaults(handler=command_slice_move)

    slice_list = slice_sub.add_parser("list", help="List configured slices")
    _add_json_flag(slice_list)
    slice_list.set_defaults(handler=command_slice_list)

    slice_enable = slice_sub.add_parser("enable", help="Enable slicing")
    _add_json_flag(slice_enable)
    slice_enable.set_defaults(handler=command_slice_enable, enabled=True)

    slice_disable = slice_sub.add_parser("disable", help="Disable slicing")
    _add_json_flag(slice_disable)
    slice_disable.set_defaults(handler=command_slice_enable, enabled=False)

    slice_remainder = slice_sub.add_parser(
        "remainder-name", help="Set the name of the final (unsliced) piece"
    )
    slice_remainder.add_argument("name")
    _add_json_flag(slice_remainder)
    slice_remainder.set_defaults(handler=command_slice_remainder_name)

    # generate
    generate_parser = subparsers.add_parser(
        "generate", help="Run the full pipeline and export the generated body"
    )
    generate_parser.add_argument("project")
    generate_parser.add_argument("--output", "-o", required=True)
    generate_parser.add_argument("--fitcheck")
    generate_parser.add_argument("--slice-dir")
    generate_parser.add_argument("--force", action="store_true")
    _add_json_flag(generate_parser)
    generate_parser.set_defaults(handler=command_generate)

    # validate
    validate = subparsers.add_parser("validate", help="Run geometric validation without exporting")
    validate.add_argument("project")
    _add_json_flag(validate)
    validate.set_defaults(handler=command_validate)

    # export
    export = subparsers.add_parser(
        "export", help="Generate and export a single artifact (STEP, STL, fit-check, or package)"
    )
    export.add_argument("project")
    export.add_argument("output", help="Output file (or directory when --target package)")
    export.add_argument(
        "--target",
        default="step",
        choices=["step", "stl", "fitcheck", "package"],
        help="What to export (default: step)",
    )
    export.add_argument("--force", action="store_true", help="Export even with validation errors")
    _add_json_flag(export)
    export.set_defaults(handler=command_export)

    # render
    render = subparsers.add_parser("render", help="Render a PNG preview without a desktop session")
    render.add_argument("project")
    render.add_argument("output", help="Output PNG path")
    render.add_argument("--view", default="iso", choices=["iso", "top", "front", "side"])
    render.add_argument("--width", type=int, default=1600)
    render.add_argument("--height", type=int, default=1000)
    render.add_argument("--no-envelope", action="store_true", help="Hide the envelope wireframe")
    render.add_argument(
        "--generate",
        action="store_true",
        help="Run generation first and render the resulting solid instead of the raw scene",
    )
    _add_json_flag(render)
    render.set_defaults(handler=command_render)

    # doctor
    doctor = subparsers.add_parser("doctor", help="Check that the CAD/rendering environment is healthy")
    _add_json_flag(doctor)
    doctor.set_defaults(handler=command_doctor)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        args = parser.parse_args(["gui"] + (argv or []))
    try:
        return int(args.handler(args))
    except CliError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except (CommandError, ProjectIoError, ImportGeometryError, GenerationError, ExportError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def run(argv: list[str] | None = None) -> None:
    """Process entry point used by both ``python -m flipfill`` and the
    ``flipfill`` console script.

    The OpenCascade bindings this project depends on (``cadquery``/OCP) crash
    the interpreter with a native access violation during Python's own
    finalization on some platform/Python combinations, *after* every command
    has already run to completion correctly. That corrupts the process exit
    code and would make every CI job that shells out to ``flipfill`` look
    like a failure even when it succeeded. Determine the real exit code
    ourselves, flush output, then terminate immediately with
    :func:`os._exit` so Python's normal (and here, unreliable) interpreter
    teardown never runs.
    """

    try:
        code = main(argv)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        code = 130
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
