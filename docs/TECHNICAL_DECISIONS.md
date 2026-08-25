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

## Primary technical sources

- CadQuery documentation: https://cadquery.readthedocs.io/
- CadQuery imports/exports: https://cadquery.readthedocs.io/en/latest/importexport.html
- CadQuery assemblies: https://cadquery.readthedocs.io/en/latest/assy.html
- CadQuery repository/releases: https://github.com/CadQuery/cadquery
- OCP releases: https://github.com/CadQuery/OCP/releases
- OpenCascade offset API: https://dev.opencascade.org/doc/refman/html/class_b_rep_offset_a_p_i___make_offset_shape.html
- OpenCascade STEP assembly reader: https://dev.opencascade.org/doc/refman/html/class_s_t_e_p_c_a_f_control___reader.html
- VTK: https://vtk.org/
