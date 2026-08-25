# Contributing

FlipFill CAD is intentionally split into a functional geometry core and a thin desktop shell. Geometry behavior must remain usable from both the GUI and CLI.

## Development setup

```bash
./scripts/bootstrap.sh
.venv/bin/python -m pytest
.venv/bin/python -m ruff check .
```

On Windows, use `scripts/bootstrap.ps1` and `.venv\Scripts\python.exe`.

## Design rules

- Treat every physical volume as an explicit scene object with an explicit role.
- Never hide a failed offset or Boolean. Report it, preserve diagnostics, and use only documented fallbacks.
- Keep millimeters and world-coordinate transforms consistent at every boundary.
- Add a geometry regression test for every kernel bug or corrected enclosure failure.
- Keep the core free of GUI state so headless generation remains deterministic.
- Export a fit-check assembly whenever a workflow produces production geometry.

## Pull requests

Include tests, update the relevant semantic or architecture document, and describe which CAD invariants the change preserves. For new geometry features, include a small reproducible project under `examples/` or `tests/fixtures/`.
