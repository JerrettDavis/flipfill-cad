# Roadmap

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
- Add oriented bounding-box and convex-hull cavity modes.
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
