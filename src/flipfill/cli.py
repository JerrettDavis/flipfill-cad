from __future__ import annotations

import argparse
import sys
from pathlib import Path

from flipfill.geometry.exporters import export_fitcheck_assembly, export_shape
from flipfill.geometry.generator import MessageLevel, generate
from flipfill.geometry.importers import GeometryRepository
from flipfill.project_io import load_project


def _print_messages(messages) -> None:
    for message in messages:
        prefix = message.level.value.upper()
        object_suffix = f" [{message.object_id}]" if message.object_id else ""
        print(f"{prefix}{object_suffix}: {message.message}")


def command_generate(args: argparse.Namespace) -> int:
    project = load_project(args.project)
    repository = GeometryRepository()
    generated = generate(project, repository)
    _print_messages(generated.messages)

    errors = [m for m in generated.messages if m.level is MessageLevel.ERROR]
    if errors and not args.force:
        print("Generation contains validation errors; use --force to export anyway.", file=sys.stderr)
        return 2

    output = export_shape(generated.result, args.output)
    print(f"Exported generated body: {output}")

    if args.fitcheck:
        assembly = export_fitcheck_assembly(project, generated, args.fitcheck)
        print(f"Exported fit-check assembly: {assembly}")

    if project.split.enabled and generated.split_a is not None and generated.split_b is not None:
        split_dir = Path(args.split_dir or Path(args.output).parent).resolve()
        split_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(args.output).stem
        first = export_shape(generated.split_a, split_dir / f"{stem}_A.step")
        second = export_shape(generated.split_b, split_dir / f"{stem}_B.step")
        print(f"Exported split halves: {first}, {second}")

    return 0


def command_validate(args: argparse.Namespace) -> int:
    project = load_project(args.project)
    generated = generate(project, GeometryRepository())
    _print_messages(generated.messages)
    errors = [m for m in generated.messages if m.level is MessageLevel.ERROR]
    print(
        f"Result valid={generated.result.isValid()} "
        f"volume={generated.result.Volume():.3f} mm³ "
        f"warnings={len(generated.warnings)} errors={len(errors)}"
    )
    return 1 if errors else 0


def command_gui(args: argparse.Namespace) -> int:
    from flipfill.ui.app import run_app

    return run_app(args.project)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flipfill",
        description="Generate clearance-first enclosure solids from positioned CAD objects.",
    )
    subparsers = parser.add_subparsers(dest="command")

    gui = subparsers.add_parser("gui", help="Launch the desktop application")
    gui.add_argument("project", nargs="?", help="Optional .flipfill.json project")
    gui.set_defaults(handler=command_gui)

    generate_parser = subparsers.add_parser(
        "generate", help="Generate and export a project headlessly"
    )
    generate_parser.add_argument("project")
    generate_parser.add_argument("--output", "-o", required=True)
    generate_parser.add_argument("--fitcheck")
    generate_parser.add_argument("--split-dir")
    generate_parser.add_argument("--force", action="store_true")
    generate_parser.set_defaults(handler=command_generate)

    validate = subparsers.add_parser("validate", help="Run geometric validation")
    validate.add_argument("project")
    validate.set_defaults(handler=command_validate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        args = parser.parse_args(["gui"] + (argv or []))
    return int(args.handler(args))
