# Changelog

## Unreleased

- Added the full CLI command surface: `new`, `import`, `list`, `inspect`,
  `move`, `rotate`, `align`, `role`, `clearance`, `blocker`, `envelope`,
  `split`, `export`, `render`, and `doctor`, alongside the existing
  `generate`/`validate`/`gui`. Every command supports `--json` and returns
  a meaningful exit code.
- Added `flipfill.commands`, an application service layer shared by every
  front end so scene-mutation logic isn't duplicated per CLI/GUI.
- Added `flipfill.rendering.SceneRenderer`, a Tk-independent off-screen VTK
  scene builder shared by the desktop viewport and the new `flipfill
  render` command.
- Added CLI integration tests, a CLI-driven end-to-end workflow test, a
  deterministic golden regression test, and malformed-input/error-path
  tests (31 new tests, 50 total).
- Added CI coverage reporting, a package/build-verification job for both
  platforms, and a tagged-release workflow that publishes GitHub Releases.
- Added the remaining OSS scaffolding: issue forms, PR template,
  CODEOWNERS, Dependabot, SECURITY.md, CODE_OF_CONDUCT.md.
- Fixed a native access-violation crash on interpreter shutdown (importing
  cadquery/OCP) that corrupted the exit code of every CLI invocation and
  test run on some platforms.
- Fixed `flipfill doctor`'s off-screen-rendering check crashing the whole
  process on environments with no usable OpenGL context, by isolating that
  probe in a subprocess.

## 0.1.0 - 2026-08-25

- Added STEP/STP, BREP, and IGES import through OpenCascade.
- Added STL/OBJ/PLY/OFF/3MF/glTF mesh-reference import with robust AABB Boolean proxies.
- Added numeric positioning and rotation for all scene objects.
- Added occupant, cutout, additive, and reference semantics.
- Added box, rounded-box, cylinder, and slot primitives.
- Added exact, OpenCascade-offset, and AABB clearance modes with fallback reporting.
- Added auto-fit and manual rounded-box envelopes.
- Added inverse-fill generation, BRep validity checks, cavity/result collision checks, and occupant overlap checks.
- Added optional X/Y/Z planar splitting.
- Added STEP, STL, BREP, and fit-check STEP assembly export.
- Added a cross-platform Tk/VTK desktop UI with off-screen rendering, picking, orbit, pan, zoom, and screenshots.
- Added headless generate and validate commands.
- Added a complete portable display/battery/speaker example and 19 automated tests.
