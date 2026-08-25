# Roadmap

## Since 0.1: CLI completeness pass

Delivered ahead of the 0.2 items below, because a scriptable CLI is the
primary interface and was the biggest usability gap:

- Full CLI command surface: `new`, `import`, `list`, `inspect`, `move`,
  `rotate`, `align`, `role`, `clearance`, `blocker`, `envelope`, `split`,
  `generate`, `validate`, `export`, `render`, `doctor`, `gui`. Every command
  supports `--json` and returns a meaningful exit code.
- `flipfill.commands`: an application service layer shared by the CLI (and
  the next thing to wire into the GUI) so scene-mutation logic — not just
  rendering — has one implementation instead of one per front end.
- `flipfill.rendering.SceneRenderer`: the desktop viewport and the new
  headless `flipfill render` command now share one off-screen VTK pipeline.
- `flipfill doctor`: checks cadquery/OCP/trimesh/VTK/Tk/off-screen-rendering
  health in one command, for fast triage on a new machine or in CI.
- CLI integration tests, a true CLI-driven end-to-end workflow test, a
  deterministic golden regression test on the shipped example project, and
  malformed-input/error-path tests (`tests/test_cli.py`, `test_e2e.py`,
  `test_golden.py`, `test_errors.py`).
- Fixed a native access-violation crash on interpreter shutdown (importing
  cadquery/OCP) that was corrupting the exit code of every CLI invocation
  and test run on at least one Windows/Python 3.13 environment — see
  ADR-006 in `TECHNICAL_DECISIONS.md`.
- Added an OBB (`clearance-mode obb`) clearance strategy: a PCA-fitted
  oriented bounding box, expanded by clearance and subtracted, for both
  BRep and mesh occupants. Tighter than AABB for anything rotated off the
  world axes, without the offset-safety risk of the Offset mode. Not the
  minimum-volume box (no convex-hull rotating calipers), and the *envelope*
  auto-fit is still axis-aligned only — this is occupant/cutout clearance,
  not the enclosure exterior.
- Still open from this pass, carried into 0.2 below: `align` only supports
  min/center/max on one axis at a time (no distribute/mate-face/
  surface-offset yet); `commands.py` is not yet consumed by the desktop UI,
  so scene-mutation logic is still technically duplicated between the two
  front ends even though the CLI side is now centralized; project
  `schema_version` has no migration path — `Project.from_dict` hard-rejects
  anything other than `1`.

## 0.1: Working vertical slice

Delivered in this repository:

- import;
- position;
- classify;
- fit envelope;
- create blockers/additives;
- inverse fill;
- validate;
- split;
- export STEP/STL and fit-check assembly;
- save projects;
- desktop and headless execution.

## 0.2: Mechanical assembly features

- Preserve STEP assembly trees, names, and colors.
- Add a dedicated fit-check assembly group for generated clearance bodies, separate from nominal hardware and blockers.
- Add transform gizmo and snap increments.
- Add align, distribute, mate-face, center-to-center, and surface-offset commands.
- Add convex-hull cavity mode (oriented bounding box shipped ahead of 0.2 — see above).
- Add cable sweep/path blockers and battery swelling profiles.
- Add local-coordinate envelope fitting.
- Move expensive operations into cancellable workers.
- Add project bundle format with copied assets.
- Add undo/redo command history.

## 0.3: Enclosure construction

- Front/back and left/right shell templates.
- Configurable wall thickness and interior hollowing independent of occupants.
- Tongue-and-groove, lap, rabbet, and gasket seams.
- Screw bosses, heat-set insert seats, captive nuts, and tool-access rules.
- Snap-fit hooks with material presets.
- Magnet pockets and alignment pins.
- Hinges and kickstands with swept-motion keep-outs.
- Speaker chambers and parametric grille patterns.
- Ventilation patterns with fan and airflow blockers.
- Mounting-hole recognition from imported boards.

## 0.4: Analysis and quality

- Minimum wall-thickness sampling and heat map.
- Draft/overhang and print-orientation checks.
- Non-manifold and trapped-volume diagnosis.
- Automatic section views and interference reports.
- Tolerance presets by process: FDM, resin, CNC, sheet, molding.
- Golden STEP regression corpus and kernel-version comparison.
- Deterministic operation log and replay.

## 0.5: Parametric product families

- Named parameters and expressions.
- Reusable component templates.
- Variant matrices for alternate displays, batteries, speakers, and boards.
- Constraint-based placement.
- Batch generation from CSV/JSON.
- Script/plugin SDK.
- Agent-safe command protocol over JSON-RPC.

## 1.0 criteria

- A complete enclosure can be generated, split, fastened, validated, and exported without downstream CAD for common rectangular electronics projects.
- Every generated feature is represented in a deterministic project history.
- Kernel failures are diagnosable and recoverable.
- Windows, Linux, and macOS packages are reproducible and signed.
- A representative hardware corpus passes geometric and visual regression suites.
