# Test Plan

## Current automated coverage

The release includes tests for:

- project serialization round-trip (`test_model.py`);
- primitive validity and dimensions, negative-dimension rejection (`test_primitives.py`);
- inverse-fill volume, AABB/offset/exact clearance, exterior cutout behavior,
  additive fusion, envelope fit and margins, plane and object slice-cutter
  volume and validity, occupant-overlap warning (`test_generator.py`);
- relative project paths, STEP import/generation/export/reimport,
  fit-check assembly export, mesh import with AABB Boolean proxy
  (`test_io_and_export.py`);
- every CLI command (`new` through `doctor`) including `--json` output
  shape and nonzero exit codes on failure (`test_cli.py`);
- a true end-to-end workflow driven only through the CLI — create, import,
  position, classify, block, fit, slice, validate zero unintended
  intersections, generate, export, reopen, reimport and verify every
  artifact (`test_e2e.py`);
- a deterministic golden regression test pinning the generated/sliced
  volumes of the shipped `portable_monitor_demo` example (`test_golden.py`);
- malformed project JSON, unsupported schema versions, unknown enum
  values, and other error paths (`test_errors.py`);
- a Gherkin/`pytest-bdd` end-to-end scenario for the slice tool
  (`tests/features/slicing.feature`, `tests/test_slicing_bdd.py`),
  driven through `flipfill.commands` exactly like `test_e2e.py` drives
  the CLI — no mocking.

Every test performs real geometry operations. No CAD-kernel behavior is mocked.

## Still open from this plan

- GUI smoke tests beyond "does the process start under Xvfb" (no
  interaction-level Tk automation yet).
- The fixture corpus below (multi-solid, assembly, IGES, non-manifold,
  high-face-count, offset-hostile, non-mm-unit fixtures) — today's fixtures
  are the three `examples/assets/*.step` demo parts plus ad-hoc boxes
  generated in tests.
- Visual/perceptual regression on rendered images.
- `mypy` is configured but not wired into CI (see `docs/TECHNICAL_DECISIONS.md`
  ADR list — blocked on a third-party stub bug in `casadi`, not our code).

## CI matrix

The workflow (`.github/workflows/ci.yml`) targets:

- Windows and Ubuntu;
- Python 3.11, 3.12, and 3.13;
- unit/integration tests with coverage collection;
- static linting (ruff);
- Linux GUI startup under Xvfb; and
- a separate `build` job that bootstraps and PyInstaller-packages both
  platforms on every push/PR, verifying the packaged entry point exists.

`.github/workflows/release.yml` builds and publishes both platform packages
to a GitHub Release whenever a `v*.*.*` tag is pushed.

## Required fixture corpus for 0.2

- simple single-solid STEP;
- multi-solid compound;
- named/color STEP assembly;
- IGES solid;
- open shell;
- non-manifold or invalid BRep;
- high-face-count board model;
- filleted battery pouch;
- connector with small-radius detail;
- offset-hostile C0/B-spline body;
- STL/OBJ scene with multiple meshes;
- units other than millimeters;
- source paths containing spaces and Unicode.

## Geometric regression strategy

For generated outputs, store and compare:

- BRep validity;
- solid count;
- volume;
- area;
- bounding box;
- cavity intersection volumes;
- sliced-body volumes; and
- tessellated triangle count within a tolerance band.

STEP files should not be compared byte-for-byte because exporter metadata and entity ordering can change between kernel versions.

## Visual regression

Render fixed cameras for the demo corpus and compare normalized images with a perceptual threshold. Render layers separately:

- references and occupants;
- clearances;
- blockers;
- envelope;
- generated result; and
- sliced bodies.

## Manual release checklist

- Import a real vendor display STEP.
- Import or create a battery proxy.
- Position a speaker without clearance overlap.
- Fit the envelope.
- Add a screen aperture and USB blocker.
- Generate without errors.
- Export generated and fit-check STEP.
- Open both in Fusion 360.
- Inspect sections through the screen, battery, port, speaker, and seam.
- Export STL and verify slicer manifold status.
