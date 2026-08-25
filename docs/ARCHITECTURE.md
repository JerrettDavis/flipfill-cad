# Architecture

## Overview

FlipFill is split into a functional CAD core and an imperative desktop shell.

```text
┌──────────────────────────────────────────────────────────┐
│ Desktop UI (Tk)                 CLI / CI                  │
│ scene tree, inspector,         validate, generate,       │
│ viewport, file dialogs         export                    │
└──────────────────────────┬───────────────────────────────┘
                           │ Project model
┌──────────────────────────▼───────────────────────────────┐
│ Application services                                    │
│ project I/O, geometry repository, fit, generation,       │
│ validation, split, export                               │
└──────────────────────────┬───────────────────────────────┘
                           │ CadQuery shapes / meshes
┌──────────────────────────▼───────────────────────────────┐
│ Geometry adapters                                       │
│ STEP/BREP/IGES import, mesh reference import,            │
│ primitive construction, transform, offset, tessellation │
└──────────────────────────┬───────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────┐
│ OpenCascade BRep kernel          VTK renderer            │
│ Booleans, STEP, topology         tessellated preview     │
└──────────────────────────────────────────────────────────┘
```

## Package responsibilities

### `flipfill.model`

Pure dataclasses and enums for project state. The model is JSON-serializable and contains no renderer or file handle.

### `flipfill.project_io`

Loads and saves schema-versioned JSON. Relative source paths are resolved against the project location.

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

### `flipfill.ui.viewport`

Renders VTK off-screen, converts the framebuffer to a Pillow image, and displays it in Tk. This avoids VTK's optional native Tk bridge while retaining local orbit, pan, zoom, picking, and screenshots.

### `flipfill.ui.app`

Coordinates user interaction, scene state, generation, reporting, and export.

## Dependency direction

The domain model has no dependency on CadQuery, VTK, Tk, or Trimesh. Geometry depends on the model. UI and CLI depend on geometry. The core never calls the UI.

## Extensibility seams

- New source formats can be added behind `GeometryRepository`.
- New primitive types can be added behind `make_primitive` and `PrimitiveKind`.
- New clearance strategies can be added behind `_subtractive_shape`.
- New envelope generators can implement the same BRep-returning contract.
- Additional validators append `GenerationMessage` values.
- Alternative UIs can consume the same `Project` and `GenerationResult` types.

## Persistence

Project schema version 1 stores source references and parameters, not serialized OpenCascade bodies. This keeps project files reviewable and permits deterministic regeneration. A bundle format can later zip the JSON and copied source assets.

## Threading

Release 0.1 runs Booleans on the UI thread. This keeps the prototype simple but can pause during large STEP operations. The next milestone moves import, offset, generate, and export into cancellable worker processes because OpenCascade jobs are CPU-bound and process isolation is safer than attempting to interrupt a kernel operation in a GUI thread.
