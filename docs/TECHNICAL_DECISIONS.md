# Technical Decisions

## ADR-001: OpenCascade BRep as the source of truth

STEP output must remain editable in downstream CAD. Therefore the generated model is a boundary representation, not merely a triangle mesh or voxel field.

CadQuery wraps OpenCascade with a concise Python API and supports STEP import/export and assemblies. OpenCascade's current Python bindings are distributed by the CadQuery OCP project.

## ADR-002: Python for the first vertical slice

The critical risk is CAD-kernel behavior, not application boilerplate. Python provides direct access to CadQuery/OCP and enables rapid geometry tests. The functional core and JSON project model keep the option open for a future .NET/Avalonia shell or service boundary without rewriting the geometry semantics.

## ADR-003: Standard Tk UI with off-screen VTK

PySide6 is a strong long-term desktop option, but it adds another large native runtime. VTK's native Tk interactor is also absent from many wheels. The prototype uses standard Tk and renders VTK into an image buffer. This is portable, testable under Xvfb, and removes the missing-library failure while preserving local 3D interaction.

## ADR-004: Conservative AABB is a feature, not merely a fallback

Exact geometry can include component-detail cavities that are undesirable in a printed enclosure and can make offsets fragile. AABB clearances provide predictable service volume for many electronics components. Future oriented boxes and hulls will add fidelity without sacrificing robustness.

## ADR-005: Export fit-check assemblies

A successful Boolean is not proof of a useful enclosure. Exporting the result and hardware together allows independent inspection, sectioning, and measurement in Fusion 360.

## ADR-006: os._exit() at the real process entry point, not inside main()

Importing `cadquery`/OCP has been observed to crash the interpreter with a
native access violation during Python's own finalization, on at least one
real Windows/Python 3.13 environment, well after every command has already
completed correctly. Left alone this corrupts the process exit code, which
would make every scripted `flipfill` call and every CI test run look like a
failure regardless of what actually happened -- unacceptable for a CLI-first
tool whose whole value proposition is scriptability.

The fix is `os._exit()` at the outermost boundary: `flipfill.cli.run()` (the
`flipfill` console script and `python -m flipfill` both call this, not
`main()`) and a `pytest_unconfigure` hook in `tests/conftest.py`, each
determining the real exit code, flushing stdout/stderr, then terminating
immediately -- skipping Python's normal, here-unreliable, interpreter
teardown. `flipfill.cli.main()` itself stays a normal function that returns
an `int` and never exits the process, so library and test code that calls it
directly (see `tests/test_cli.py`) is unaffected.

This is a workaround for third-party native code, not a fix for our own; it
should be revisited (and likely removed) once upstream `cadquery`/OCP wheels
resolve the underlying shutdown bug. See `docs/ARCHITECTURE.md` for where
each hook lives.

## ADR-007: Slicing is a breaking replacement for split, not an addition

The 0.1 planar split (`SplitSpec`: enabled/axis/offset/gap, exactly two
named halves) could not express more than two bodies or a non-axis-aligned
cut, and real enclosures routinely need three or more (front bezel,
center support, rear shell). Keeping `SplitSpec` alongside a new general
mechanism would mean two overlapping body-producing code paths in the
generator, CLI, and UI to maintain and explain. Since `Project` has no
schema-migration path yet (`schema_version` hard-rejects anything but
`1`; see ADR list and `docs/ROADMAP.md`), and the project is pre-1.0,
`split` was removed outright in favor of `slicing`: an ordered list of
plane-or-object cuts producing N named bodies. Existing `.flipfill.json`
files with a `split` key silently lose that setting on load (the key is
simply not read); there is no automatic migration.

## Primary technical sources

- CadQuery documentation: https://cadquery.readthedocs.io/
- CadQuery imports/exports: https://cadquery.readthedocs.io/en/latest/importexport.html
- CadQuery assemblies: https://cadquery.readthedocs.io/en/latest/assy.html
- CadQuery repository/releases: https://github.com/CadQuery/cadquery
- OCP releases: https://github.com/CadQuery/OCP/releases
- OpenCascade offset API: https://dev.opencascade.org/doc/refman/html/class_b_rep_offset_a_p_i___make_offset_shape.html
- OpenCascade STEP assembly reader: https://dev.opencascade.org/doc/refman/html/class_s_t_e_p_c_a_f_control___reader.html
- VTK: https://vtk.org/
