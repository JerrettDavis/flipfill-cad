# Test Plan

## Current automated coverage

The release includes tests for:

- project serialization round-trip;
- primitive validity and dimensions;
- negative-dimension rejection;
- inverse-fill volume;
- AABB clearance volume;
- OpenCascade exact-offset execution;
- exterior cutout behavior;
- additive fusion;
- envelope fit and margins;
- planar split volume and validity;
- occupant-overlap warning;
- relative project paths;
- STEP import, generation, export, and reimport;
- fit-check assembly export; and
- mesh import with AABB Boolean proxy.

Every test performs real geometry operations. No CAD-kernel behavior is mocked.

## CI matrix

The workflow targets:

- Windows and Ubuntu;
- Python 3.11, 3.12, and 3.13;
- unit/integration tests;
- static linting; and
- Linux GUI startup under Xvfb.

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
- split-half volumes; and
- tessellated triangle count within a tolerance band.

STEP files should not be compared byte-for-byte because exporter metadata and entity ordering can change between kernel versions.

## Visual regression

Render fixed cameras for the demo corpus and compare normalized images with a perceptual threshold. Render layers separately:

- references and occupants;
- clearances;
- blockers;
- envelope;
- generated result; and
- split halves.

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
