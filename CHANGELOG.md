# Changelog

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
