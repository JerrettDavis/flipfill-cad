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

The transformed world-axis-aligned bounds are expanded by the clearance amount and subtracted. This sacrifices local fidelity for predictability. It is often the correct early enclosure abstraction for rectangular screens, batteries, board assemblies, speakers, and wiring zones.

Future releases will add oriented bounding boxes, convex hulls, swept cable volumes, and face-specific clearance.

## Envelope

The 0.1 envelope is a box or an XY rounded rectangle extruded through Z. Auto-fit unions the world bounds of included non-cutout objects and expands them by separate X/Y/Z margins.

Auto-fit is intentionally axis-aligned and resets envelope rotation to zero. Manual envelope rotation remains available after fitting, but a rotated envelope should be checked carefully because automatic local-coordinate fitting is not yet implemented.

## Generation order

```text
base = envelope
positive = fuse(base, every additive)
result = cut(positive, every occupant cavity, every cutout blocker)
```

Booleans use the project's tolerance. The resulting shape is cleaned and checked for validity.

## Validation invariants

- The generated BRep must be valid.
- The generated body must have positive volume.
- Generated material must have zero volumetric intersection with every occupant cavity.
- An occupant extending outside the envelope is reported.
- Occupant clearances with positive-volume overlap are reported.
- A cutout that does not intersect the envelope is reported.
- Split halves must both be nonempty valid shapes.

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
