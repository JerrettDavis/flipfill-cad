# Architecture

## Overview

FlipFill is split into a functional CAD core, a shared application-service
layer, and two thin front ends (CLI, desktop UI) that both drive it.

```text
┌──────────────────────────────────────────────────────────┐
│ Desktop UI (Tk)                 CLI (argparse)            │
│ scene tree, inspector,         new, import, move, align, │
│ viewport, file dialogs         generate, export, render… │
└──────────────────────────┬───────────────────────────────┘
                           │ Project model
┌──────────────────────────▼───────────────────────────────┐
│ flipfill.commands (application service layer)             │
│ create/open project, import, find/move/rotate/align,      │
│ role/clearance, blocker primitives, envelope, split,       │
│ doctor -- no console I/O, no sys.exit, unit-testable        │
└──────────────────────────┬───────────────────────────────┘
                           │ CadQuery shapes / meshes
┌──────────────────────────▼───────────────────────────────┐
│ Geometry adapters                                       │
│ STEP/BREP/IGES import, mesh reference import,            │
│ primitive construction, transform, offset, tessellation,│
│ generation (fit/fuse/cut/validate/split)                 │
└──────────────────────────┬───────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────┐
│ OpenCascade BRep kernel          VTK renderer            │
│ Booleans, STEP, topology         (flipfill.rendering)    │
└──────────────────────────────────────────────────────────┘
```

## Package responsibilities

### `flipfill.model`

Pure dataclasses and `enum.StrEnum`s for project state. The model is JSON-serializable and contains no renderer or file handle.

### `flipfill.project_io`

Loads and saves schema-versioned JSON. Relative source paths are resolved against the project location.

### `flipfill.commands`

The application service layer shared by every front end: `create_project`, `open_project`, `find_object`, `import_geometry`, `list_objects`/`inspect_object`, `move_object`/`rotate_object`, `align_object`, `set_role`/`set_clearance`, `add_primitive_object`, `configure_envelope`/`fit_envelope`, `configure_split`, and `run_doctor`. Every function operates on plain `flipfill.model` types, performs no console I/O, and raises `CommandError` for user-facing problems -- so it is unit-testable directly and there is exactly one place that knows how to, say, resolve an object reference or align a bounding-box edge. `cli.py` is the only consumer today; the desktop UI is the next one, closing the last GUI/CLI logic duplication (scene mutation, not just rendering).

### `flipfill.geometry.align`

Pure bounding-box axis/edge math (`axis_index`, `bound_value`) used by `commands.align_object`. Kept separate from `commands` because it is reusable, dependency-free geometry math, not orchestration.

### `flipfill.geometry.importers`

Loads immutable source geometry and caches it by resolved path. It supports BRep assets and triangle-mesh references. Scene transforms are applied during resolution.

### `flipfill.geometry.primitives`

Creates BRep box, rounded-box, cylinder, and slot primitives.

### `flipfill.geometry.offsets`

Isolates OpenCascade 3D offset behavior and failure handling.

### `flipfill.geometry.generator`

Contains the central use cases:

- fit envelope;
- resolve Boolean shapes;
- fuse additives;
- subtract cavities and cutouts;
- validate invariants; and
- split the generated body.

The generator has no GUI dependency and is exercised directly by tests and the CLI.

### `flipfill.geometry.exporters`

Exports generated bodies and named fit-check assemblies.

### `flipfill.geometry.tessellation`

Converts BRep shapes into renderable triangles without changing the source geometry.

### `flipfill.rendering`

`SceneRenderer`: builds and rasterizes a FlipFill scene (envelope, objects, generated result, ground grid, axes) with an off-screen VTK pipeline. Has no dependency on Tk, so it is the single place that turns a `Project`/`GenerationResult` pair into pixels for *both* the desktop viewport and the headless `flipfill render` CLI command -- neither one re-implements tessellation, color, or camera logic.

### `flipfill.ui.viewport`

Wraps a `SceneRenderer` in a Tk `Canvas`: converts each off-screen frame to a Pillow image, and owns mouse-driven orbit/pan/zoom/picking. This avoids VTK's optional native Tk bridge while retaining local 3D interaction.

### `flipfill.ui.app`

Coordinates user interaction, scene state, generation, reporting, and export.

## Dependency direction

The domain model has no dependency on CadQuery, VTK, Tk, or Trimesh. Geometry depends on the model. `commands` depends on geometry and the model. The CLI depends on `commands`. UI depends on geometry and rendering directly today (see `commands` above); it does not, and should not, re-implement geometry math. The core never calls the UI.

## Extensibility seams

- New source formats can be added behind `GeometryRepository`.
- New primitive types can be added behind `make_primitive` and `PrimitiveKind`.
- New clearance strategies can be added behind `_subtractive_shape`.
- New envelope generators can implement the same BRep-returning contract.
- Additional validators append `GenerationMessage` values.
- Alternative UIs or automations can consume `flipfill.commands` directly instead of shelling out to the CLI.

## Persistence

Project schema version 1 stores source references and parameters, not serialized OpenCascade bodies. This keeps project files reviewable and permits deterministic regeneration. There is no migration path yet: `Project.from_dict` hard-rejects any `schema_version` other than `1` (see `docs/ROADMAP.md`). A bundle format can later zip the JSON and copied source assets.

## Threading

Release 0.1 runs Booleans on the UI thread. This keeps the prototype simple but can pause during large STEP operations. The next milestone moves import, offset, generate, and export into cancellable worker processes because OpenCascade jobs are CPU-bound and process isolation is safer than attempting to interrupt a kernel operation in a GUI thread.

## A note on process exit reliability

On at least one verified environment (Windows, Python 3.13.13, `cadquery` 2.8.0 / `cadquery-ocp` 7.9.3.1.1), importing `cadquery`/OCP crashes the interpreter with a native access violation (`STATUS_ACCESS_VIOLATION`) during Python's own finalization -- *after* the program has already completed correctly. Left alone, this corrupts the process exit code: every `flipfill` invocation and every `pytest` run would look like a failure to a calling shell or CI job even though it printed correct output and succeeded. `flipfill.cli.run()` (the actual process entry point for both `python -m flipfill` and the `flipfill` console script) and a `pytest_unconfigure` hook in `tests/conftest.py` work around this by determining the real exit code themselves, flushing output, and calling `os._exit()` before Python's normal (here, unreliable) teardown runs. `flipfill.cli.main()` itself is unaffected and still returns normally for library/test use. See ADR-006.
