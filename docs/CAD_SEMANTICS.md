# CAD Semantics

## Coordinate convention

FlipFill uses millimeters. X, Y, and Z are not assigned product-specific meanings. For handheld electronics, a useful convention is:

- X: device width;
- Y: device height;
- Z: front-to-back thickness.

All imported geometry and primitives are transformed into world coordinates before fitting, rendering, validation, and Boolean generation.

## Scene roles

### Occupant

An occupant represents physical space that generated material must not enter. Examples include:

- screen and touch stack;
- PCB and rear components;
- battery pouch, including swelling allowance;
- speaker body and acoustic chamber;
- connector body;
- cable and bend radius;
- removable media envelope;
- antenna keep-out;
- tool or finger service volume.

Occupants are subtracted after clearance is applied.

### Cutout

A cutout represents an explicit removal path. Unlike an occupant, a cutout often extends beyond the outer envelope. Examples include screen apertures, USB openings, vents, grilles, button probe holes, and screw-driver access.

### Additive

An additive is fused to the envelope before subtraction. Examples include a mounting boss, rib, hinge pad, stand mount, or lanyard reinforcement.

Occupants are subtracted after additives are fused, so an additive that intrudes into an occupant cavity is removed. This ordering is intentional and prevents a boss from silently intersecting hardware.

### Reference

A reference participates in rendering and project persistence but not Booleans. It can represent a hand envelope, neighboring object, desk plane, or industrial-design reference.

## Clearance modes

### Exact

The transformed BRep is subtracted unchanged. Use this only when the source geometry already includes all desired tolerance and service clearance.

### Offset

OpenCascade constructs an outward 3D offset. This is the closest representation of constant normal clearance, but complex topology can make the operation fail or self-intersect. FlipFill validates the result and falls back to AABB when necessary.

### AABB

The transformed world-axis-aligned bounds are expanded by the clearance amount and subtracted. This sacrifices local fidelity for predictability. It is often the correct early enclosure abstraction for rectangular screens, batteries, board assemblies, speakers, and wiring zones. A part rotated off the world axes inflates its AABB volume — use OBB instead when that matters.

### OBB

An oriented bounding box, fitted with PCA over the resolved geometry's world-space vertices (BRep: tessellated points; mesh: the mesh vertices directly), expanded by the clearance amount and subtracted. This is deterministic and cheap, not a true minimum-volume box (that needs a convex-hull rotating-calipers search), but it stays tight for any part rotated off the world axes while keeping AABB's robustness — it never depends on the source topology being offset-safe. Prefer this over AABB whenever an occupant isn't axis-aligned; prefer AABB when you specifically want the conservative world-aligned service volume (e.g. a wiring keep-out that should be axis-aligned regardless of a connector's rotation).

Future releases will add convex hulls, swept cable volumes, and face-specific clearance.

## Envelope

The 0.1 envelope is a box or an XY rounded rectangle extruded through Z. Auto-fit unions the world bounds of included non-cutout objects and expands them by separate X/Y/Z margins.

Auto-fit is intentionally axis-aligned and resets envelope rotation to zero. Manual envelope rotation remains available after fitting, but a rotated envelope should be checked carefully because automatic local-coordinate fitting is not yet implemented.

## Slicing

`Project.slicing` holds an ordered list of cuts applied to the generated
body after fit/fuse/cut/validate. Each cut ("slice") is either:

- a **plane cutter** — an arbitrarily positioned and oriented plane. The
  side of the plane on its local -Z carves off a named piece; local +Z
  continues to the next cut, or becomes the final "remainder" piece if
  there are no more cuts. An optional `gap` (mm) removes a thin kerf slab
  centered on the plane, belonging to neither piece; or
- an **object cutter** — an existing scene object's resolved solid
  (BRep or primitive; not mesh-only) used directly as the cutting tool.
  The object is intersected with, then cut from, the running remainder.

N slices produce N+1 named bodies. Names must be unique and distinct from
the configured remainder name. Slicing runs after validation and is
independent of it: a slice failure (an empty piece, a dangling object
reference, a mesh-only object cutter) raises a generation error naming
the offending slice.

## Generation order

```text
base = envelope
positive = fuse(base, every additive)
result = cut(positive, every occupant cavity, every cutout blocker)
sliced_bodies = slice(result, every configured cut)  # when slicing is enabled
```

Booleans use the project's tolerance. The resulting shape is cleaned and checked for validity.

## Validation invariants

- The generated BRep must be valid.
- The generated body must have positive volume.
- Generated material must have zero volumetric intersection with every occupant cavity.
- An occupant extending outside the envelope is reported.
- Occupant clearances with positive-volume overlap are reported.
- A cutout that does not intersect the envelope is reported.
- Sliced bodies must all be nonempty valid shapes.

## Why blockers matter

Subtracting exact hardware alone usually produces sealed cavities. A screen, port, speaker, or removable battery needs a path to the exterior. Blockers model those paths explicitly. They also make design intent readable in the project file and fit-check assembly.

## STEP output semantics

The generated STEP contains the enclosure result. The fit-check STEP is an assembly containing:

- generated body;
- positioned BRep occupants and imported solids;
- positioned primitive occupants and clearance proxies;
- positioned BRep and primitive cutout blockers;
- positioned additives; and
- references that have BRep geometry.

Mesh-only references remain visible in FlipFill but are not written into the STEP assembly because STEP output requires BRep geometry.
