# FlipFill CAD Product Plan

## Product thesis

Designing a one-off electronics enclosure often requires more CAD expertise than the electronics project itself. The designer must import several vendor models, align them, reason about tolerances, produce internal cavities, add port and cable access, split the shell, and repeatedly inspect for collisions.

FlipFill turns that into an explicit spatial workflow:

> Position what must exist, mark what must remain empty, wrap it in a manufacturable envelope, invert the occupied space, validate it, then hand the editable STEP result to a general-purpose CAD tool.

The product is not intended to replace Fusion 360, FreeCAD, SolidWorks, or Onshape. It narrows the early enclosure problem enough that a user can reach a mechanically coherent starting solid quickly and safely.

## Primary users

### Electronics maker

Has a screen, board, battery, speaker, and connectors. May have vendor STEP files but does not want to model a case from first principles.

### Firmware engineer

Needs repeatable enclosure variants as hardware changes. Prefers parameters, project files, and headless regeneration over manual sketch recreation.

### Product prototyper

Needs a fast spatial proof before investing in detailed industrial design, fasteners, ribs, gaskets, draft, or tooling.

### Agentic CAD workflow

Needs deterministic geometry semantics that an automation agent can manipulate without operating a large general-purpose CAD UI.

## Core jobs to be done

1. Import a heterogeneous collection of hardware geometry.
2. Put every physical item in the correct coordinate frame.
3. Reserve realistic assembly and operational clearance.
4. Reserve explicit paths for ports, controls, wires, sound, air, and tools.
5. Generate a coherent editable BRep.
6. Prove that generated material does not intersect occupied volumes.
7. Export a fit-check artifact that can be inspected independently.
8. Preserve the design recipe for future variants.

## Product principles

### Mechanical truth before visual polish

Every displayed transform and clearance must use the same geometry path as the Boolean engine. Visual mockups cannot be treated as proof.

### Roles must be explicit

An object is never ambiguously “in the scene.” It is an occupant, a cutout, an additive, or a reference.

### Safe fallback beats plausible corruption

When a complex exact offset fails, the system reports it and falls back to a conservative AABB cavity. It does not hide the failure.

### Fit-check is a first-class output

A generated enclosure STEP without the positioned hardware is insufficient. The app exports both.

### General CAD remains the finishing environment

FlipFill produces a strong starting BRep. Detailed seams, snaps, bosses, gaskets, texture, draft, and manufacturing features can continue in Fusion 360 or another downstream tool.

## Release 0.1 scope

- BRep and mesh-reference import.
- Numeric transform editing.
- Four scene roles.
- Primitive blockers/additives.
- Rounded-box envelope and auto-fit.
- Exact, offset, and AABB clearance.
- Inverse-fill Boolean generation.
- Validation and collision reporting.
- Planar split.
- STEP/STL/BREP and fit-check assembly export.
- JSON project persistence.
- Desktop and headless interfaces.
- Reproducible demo and automated tests.

## Deliberate non-goals for 0.1

- Full direct-manipulation CAD constraints.
- Feature-history editing equivalent to Fusion.
- Production injection-molding analysis.
- Automatic conversion of arbitrary triangle meshes to clean BRep solids.
- Automated guarantee of printability or structural strength.
- Cloud accounts, collaboration, or telemetry.

## Success criteria

A user can take display, battery, and speaker STEP models, position them without hidden intersections, create a rounded external envelope, add screen and port blockers, generate a valid solid, split it, and import the exported STEP assembly into Fusion 360 with all key bodies aligned.

The prototype meets that behavioral slice today through the included example and test suite.
