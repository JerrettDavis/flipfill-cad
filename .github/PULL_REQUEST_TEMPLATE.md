## Summary

<!-- What does this change do, and why? -->

## CAD invariants preserved

<!--
FlipFill's geometry core has explicit invariants (see CONTRIBUTING.md and
docs/CAD_SEMANTICS.md). For any change touching flipfill.geometry or flipfill.model,
state which of these remain true and how you verified it:

- Generated BRep stays valid and STEP-exportable.
- Occupant cavities are still fully subtracted (no residual intersection).
- Failed offsets/Booleans are reported, never silently swallowed or hidden.
- Millimeters and world-coordinate transforms stay consistent at every boundary.
-->

## Test plan

- [ ] `pytest` passes locally
- [ ] `ruff check src tests examples` passes locally
- [ ] `mypy` passes locally (for changes under `src/flipfill`)
- [ ] Added/updated a regression test for this change
- [ ] For a new geometry feature: added a small reproducible project under
      `examples/` or a fixture under `tests/`

## Screenshots / exported STEP (if UI or geometry output changed)

<!-- Attach a screenshot for GUI changes, or describe what changed in exported geometry. -->
