# Slice/Cut Tool Design

Status: approved by user, pending implementation plan.

## Problem

FlipFill can generate one solid enclosure body and, today, split it into
exactly two halves along one world axis (`Project.split`: enabled/axis/
offset/gap → `GenerationResult.split_a`/`split_b`). Real enclosures are
often more than two pieces: e.g. a rounded-cube case with a screen,
battery, and screws needs a front bezel, a center support, and a
battery-pocket/rear shell as three (or more) separate printable/machinable
bodies, cut apart along several planes (or against another object used as
a cutting tool) rather than one axis-aligned split.

This spec generalizes the single two-body split into an ordered, named,
N-body slicer, replacing `SplitSpec` outright (pre-1.0, no project schema
migration path exists yet — see `docs/ROADMAP.md` and
`Project.from_dict`'s hard schema-version check).

## Scope

In scope:

- An ordered list of cuts. Each cut's tool ("cutter") is either an
  arbitrarily positioned/oriented **plane**, or a reference to an
  existing **scene object** (BRep or primitive) used as the literal
  cutting solid.
- N cuts produce N+1 named bodies from the generated result.
- CLI commands to manage the slice list, `--json` output, nonzero exit
  codes on error — matching every existing command.
- Export: one STEP (and, via export-package, STL) per named body.
- Desktop GUI wiring: a slice-list editor in the existing "Generate" tab,
  following the app's established fixed-field-panel style.
- Unit tests (model round-trip, generator algorithm, CLI) and a
  `pytest-bdd` Gherkin e2e scenario matching the case-with-bezel example.

Out of scope (explicitly deferred, not stubbed):

- Spline/sketch-curve-defined cutting surfaces. There is no 2D sketch or
  spline authoring entity anywhere in `flipfill.model` today; building
  one is a separate, larger feature and is left as a future roadmap item.
- A viewport plane gizmo / drag-to-cut interaction. Cut planes are set
  numerically (position + rotation), the same way the envelope and
  today's split plane are configured — no new 3D interaction code.
- Any project schema migration tooling. This is a breaking format change,
  consistent with how `SplitSpec` itself was never migration-guarded.

## Data model (`flipfill/model.py`)

Remove `SplitAxis`, `SplitSpec`, and `Project.split`. Add:

```python
class SliceCutterKind(StrEnum):
    PLANE = "plane"
    OBJECT = "object"


@dataclass(slots=True)
class SliceSpec:
    name: str = "Body"
    cutter_kind: SliceCutterKind = SliceCutterKind.PLANE
    # Plane cutter: the cut plane is this transform's local XY plane;
    # local +Z is the side that continues to the next cut (or becomes the
    # remainder); local -Z is carved off and named `name`.
    transform: Transform = field(default_factory=Transform)
    # Plane cutter only: kerf width in mm, like today's SplitSpec.gap — a
    # slab of this width, centered on the plane, is removed entirely
    # (belongs to neither the carved piece nor the remainder). Must be 0
    # for an object cutter (the object's own geometry defines the
    # separation instead).
    gap: float = 0.0
    # Object cutter: id of an existing SceneObject used as the cutting
    # solid. Must resolve to BRep geometry (mesh-only objects are
    # rejected the same way mesh objects are rejected as additives today).
    object_id: str | None = None

    def to_dict(self) -> dict[str, Any]: ...
    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> SliceSpec: ...


@dataclass(slots=True)
class SlicingSpec:
    enabled: bool = False
    slices: list[SliceSpec] = field(default_factory=list)
    remainder_name: str = "Remainder"

    def to_dict(self) -> dict[str, Any]: ...
    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> SlicingSpec: ...
```

`Project.slicing: SlicingSpec = field(default_factory=SlicingSpec)` replaces
`Project.split`. `Project.to_dict`/`from_dict` updated accordingly. No
`schema_version` bump — same convention as every other additive field
change so far (schema version stays at `1`; this repo's stance is that the
JSON shape can evolve without a version bump as long as `from_dict` uses
`.get()` with defaults, which every model field already does).

Validation invariants enforced at the `SliceSpec`/`SlicingSpec` level (in
`commands.add_slice`, not in the dataclass itself, matching how e.g.
`clearance_mm` bounds are enforced in `commands.py` rather than `model.py`):

- `name` must be non-empty and unique within `slices` and must not equal
  `remainder_name`.
- `cutter_kind == OBJECT` requires `object_id` to reference an existing
  `SceneObject` at validation time (existence isn't re-checked at
  generation time beyond the normal "could not resolve geometry" path
  every object already goes through).

## Generation algorithm (`flipfill/geometry/generator.py`)

Both cutter kinds resolve to one or two "knife" solids; slicing is then a
sequential intersect/cut fold over `generated.result`, replacing
`split_shape`. A plane cutter needs *two* knives (one for the isolated
piece, one for what's removed from the remainder) to reproduce today's
kerf/gap behavior; an object cutter needs only one (its own geometry is
the separation):

```python
def _local_box(size_x: float, size_y: float, z_min: float, z_max: float) -> cq.Shape:
    """A box spanning [-size_x/2, size_x/2] x [-size_y/2, size_y/2] x
    [z_min, z_max] in local coordinates, ready to be positioned by a
    Transform via transform_shape — used to build a knife whose z=0
    plane is the cutter's own plane, before it is rotated/translated
    into world space."""
    size_z = z_max - z_min
    box = cq.Workplane("XY").box(size_x, size_y, size_z, centered=True).val()
    return box.translate((0.0, 0.0, (z_min + z_max) / 2.0))


def _plane_knives(transform: Transform, gap: float, bounds: Bounds3D) -> tuple[cq.Shape, cq.Shape]:
    # Padded to the bounds diagonal, the same trick split_shape already
    # uses, but built in the plane's local frame and placed via
    # transform_shape instead of assuming a world axis.
    padding = max(bounds.size.x, bounds.size.y, bounds.size.z, 1.0) + 10.0
    half_gap = max(0.0, gap) / 2.0
    size_xy = 2.0 * padding
    piece_knife = _local_box(size_xy, size_xy, -padding, -half_gap)
    remainder_knife = _local_box(size_xy, size_xy, -padding, half_gap)
    return transform_shape(piece_knife, transform), transform_shape(remainder_knife, transform)


def _object_knife(slice_spec: SliceSpec, repository: GeometryRepository, project: Project) -> cq.Shape:
    scene_object = project.object_by_id(slice_spec.object_id)
    resolved = repository.resolve(scene_object)
    if resolved.brep is None:
        raise GenerationError(
            f"Slice '{slice_spec.name}' references an object with no BRep "
            "geometry; mesh-only objects cannot be used as a cutting tool."
        )
    return resolved.brep


def slice_result(
    result: cq.Shape,
    slicing: SlicingSpec,
    repository: GeometryRepository,
    project: Project,
    tolerance: float,
    messages: list[GenerationMessage],
) -> dict[str, cq.Shape]:
    bodies: dict[str, cq.Shape] = {}
    remainder = result
    bounds = bounds_from_shape(result)
    for slice_spec in slicing.slices:
        if slice_spec.cutter_kind is SliceCutterKind.PLANE:
            piece_knife, remainder_knife = _plane_knives(slice_spec.transform, slice_spec.gap, bounds)
        else:
            piece_knife = remainder_knife = _object_knife(slice_spec, repository, project)
        piece = _boolean_step("intersect", remainder, piece_knife, slice_spec, tolerance, messages)
        remainder = _boolean_step("cut", remainder, remainder_knife, slice_spec, tolerance, messages)
        if piece.isNull() or piece.Volume() <= tolerance:
            raise GenerationError(f"Slice '{slice_spec.name}' produced an empty body")
        bodies[slice_spec.name] = piece.clean()
    if remainder.isNull() or remainder.Volume() <= tolerance:
        raise GenerationError("Slicing consumed the entire body; the remainder is empty")
    bodies[slicing.remainder_name] = remainder.clean()
    return bodies
```

For a plane cutter with zero rotation and translation `(0, 0, offset)`,
this is exactly today's `split_shape` math (`low_plane = offset - gap/2`,
`high_plane = offset + gap/2`), just built in a local frame first —
existing golden volumes for the Z-axis split case are expected to carry
over unchanged. `_boolean_step`'s signature takes a `SceneObject` for
error attribution; `_boolean_step` itself is reused unmodified (it
already dispatches via `getattr(result, op)`, so `"intersect"` works
alongside the existing `"fuse"`/`"cut"` calls) — `slice_spec` is passed
positionally where it currently expects a `SceneObject`, so
`_boolean_step`'s parameter is renamed from `scene_object` to `owner: SceneObject | SliceSpec`
and its error-message formatting is generalized from
`f"({scene_object.role.value})"` to a small `_owner_label(owner)` helper
returning `f"({owner.role.value})"` for a `SceneObject` or
`"(slice)"` for a `SliceSpec`, since a `SliceSpec` has no `role`.

`GenerationResult.split_a`/`split_b` are removed; add
`sliced_bodies: dict[str, cq.Shape] = field(default_factory=dict)`
(insertion-ordered, so iteration order matches slice order with the
remainder last). `generate()` calls `slice_result(...)` when
`project.slicing.enabled` in place of today's `if project.split.enabled`
block, with the same try/except-to-`GenerationMessage` wrapping.

## Commands layer (`flipfill/commands.py`)

Replace `configure_split` with:

- `configure_slicing(project, *, enabled=None, remainder_name=None) -> None`
- `add_slice(project, *, name, cutter_kind, transform=None, gap=0.0, object_id=None, index=None) -> SliceSpec` —
  validates per the invariants above, raises `CommandError` otherwise;
  inserts at `index` (default: append). `gap` must be `>= 0`
  (`CommandError` otherwise, matching today's `configure_split` gap
  check) and must be `0` when `cutter_kind is SliceCutterKind.OBJECT`
  (`CommandError`: "Gap only applies to plane cutters").
- `remove_slice(project, name_or_index) -> None`
- `reorder_slice(project, name_or_index, new_index) -> None`
- `list_slices(project) -> list[SliceSpec]` (thin, for CLI `list`/`--json`)

All follow the file's existing conventions: plain `flipfill.model` types
in and out, no console I/O, `CommandError` for user-facing failures.

## CLI (`flipfill/cli.py`)

Replace the `split` subcommand with a `slice` command group (subcommands,
same style as existing single-purpose commands — no new argparse pattern
needed beyond nested subparsers, which argparse supports natively):

```
flipfill slice <project> add --name "Front Bezel" --plane --at-z 8 --gap 0.3 [--rx --ry --rz --x --y]
flipfill slice <project> add --name "Battery Pocket" --object Battery
flipfill slice <project> remove "Front Bezel"
flipfill slice <project> move "Front Bezel" --to 0
flipfill slice <project> list [--json]
flipfill slice <project> enable|disable
flipfill slice <project> remainder-name "Rear Shell"
```

`generate`/`export`/`command_export` (package mode): `--split-dir`
becomes `--slice-dir`; every `{stem}_A.step`/`{stem}_B.step` pair becomes
one `{stem}_{slug(name)}.step` per entry in `generated.sliced_bodies`
(slug: lowercase, non-alphanumeric → `_`, matching how the fit-check
assembly already names entries as `{ROLE}_{index:02d}_{name}`).

## Exporters (`flipfill/geometry/exporters.py`)

No new function required. `export_shape` already accepts any `cq.Shape`;
CLI and UI both loop over `generated.sliced_bodies.items()` and call
`export_shape` per entry, same as today's two explicit calls.

## Desktop GUI (`flipfill/ui/app.py`)

Replace the fixed "Output split" section of the Generate tab with a
slice-list editor, reusing existing widgets/patterns only:

- `ttk.Treeview` (three columns: name, cutter kind, summary) listing
  `project.slicing.slices` in order, styled like `self.tree`.
- A fixed-field editor below it for the currently selected row: name
  entry, cutter-kind `ttk.Combobox`, then either plane transform fields
  (reusing `_entry_row`, same fields as the envelope panel's
  translation/rotation) or an object-picker `ttk.Combobox` populated from
  `self.project.objects`, toggled by cutter kind.
- Buttons: **Add**, **Remove**, **Move Up**, **Move Down**, **Apply**
  (writes the edited row back via `commands.add_slice`/replacement),
  the `enabled` checkbox, and a remainder-name entry.
- `_display_generation_report` prints one volume line per
  `generated.sliced_bodies` entry (replacing the current two-line
  split-volume block).
- `export_package`/related export methods iterate `sliced_bodies` instead
  of the two hardcoded `split_a`/`split_b` exports.

## Testing plan

### Unit — `tests/test_model.py`

- `SliceSpec`/`SlicingSpec` to_dict/from_dict round-trip, including
  default values and an object-cutter entry.

### Unit — `tests/test_generator.py` (or new `tests/test_slicing.py`)

- Plane cutter splitting a known box into two pieces of known,
  independently-computed volume (mirrors today's split-volume test).
- Object cutter using a scene primitive as the knife; verify both
  resulting pieces are valid and their volumes sum to the pre-cut volume.
- Multi-slice chain: 3+ ordered cuts → N+1 valid, nonzero-volume bodies
  whose volumes sum to the whole (within `boolean_tolerance`).
- A plane cutter with a nonzero `gap`: verify the kerf slab volume is
  excluded from both resulting pieces (piece + remainder volumes sum to
  less than the pre-cut volume by approximately `gap * cross_section_area`).
- Error paths: a plane entirely outside the shape's bounds (empty piece),
  an object cutter referencing a mesh-only object, an object cutter
  referencing a nonexistent id, duplicate slice names, a nonzero `gap`
  on an object cutter (rejected in `commands.add_slice`, not here, but
  worth one generator-level test for defense in depth).

### CLI — `tests/test_cli.py`

- Every `slice` subcommand (`add` for both cutter kinds, `remove`,
  `move`, `list --json`, `enable`/`disable`, `remainder-name`),
  `--json` output shape, nonzero exit on invalid input — same coverage
  pattern as every other command in this file today.

### BDD e2e — new `tests/features/slicing.feature` + `tests/step_defs/test_slicing_steps.py`

New dev dependency: `pytest-bdd` (added to `[project.optional-dependencies].dev`
in `pyproject.toml`, alongside `pytest`/`pytest-cov`). `pytest-bdd` scenarios
are collected from a normal `test_*.py` step-definition module already
under `tests/` (via `scenarios()`), which `testpaths = ["tests"]` already
covers — no `pytest.ini_options` change needed beyond installing the plugin.

```gherkin
Feature: Slicing a generated body into multiple named parts

  Scenario: Slicing a case into front bezel, center support, and rear shell
    Given a new project with a rounded-box envelope sized like a handheld case
    And a screen, a battery, and screws positioned inside it
    When the project is generated
    And I add a horizontal slice named "Front Bezel" near the front face
    And I add a horizontal slice named "Center Support" further back
    And the project is generated again with slicing enabled
    Then generation produces three valid bodies named
      "Front Bezel", "Center Support", and "Remainder"
    And every body has positive volume
    And every body's STEP export opens as a valid solid
```

Step definitions drive everything through `flipfill.commands` (or the
CLI via `subprocess`, matching `test_e2e.py`'s existing approach) — no
Tk/UI automation. This is the closest existing analog to "BDD e2e" the
repo has (`tests/test_e2e.py`), now expressed as real Gherkin per the
user's explicit request.

### Docs to update

- `README.md`: replace the `split` CLI example/table row with `slice`.
- `docs/ARCHITECTURE.md`: extensibility-seams bullet for split → slicing.
- `docs/CAD_SEMANTICS.md`: replace the (currently absent, implied by
  README) split description with a "Slicing" section analogous to
  "Envelope"/"Clearance modes".
- `docs/ROADMAP.md`: move this out of "0.2 still open" language if any
  referenced it (it doesn't currently — `split` was 0.1 baseline); add a
  "Delivered" bullet under the current unreleased-work section, note
  spline-cut and viewport-gizmo as explicit 0.2/0.3 follow-ups.
- `docs/TEST_PLAN.md`: add the BDD suite and `pytest-bdd` to "Current
  automated coverage" and to the CI matrix description.
- `CHANGELOG.md` (if present) / repo convention: add an "Unreleased"
  entry — breaking change to project format (`split` → `slicing`).

## Risks / open questions resolved during brainstorming

- **Breaking project format change** — accepted; no migration path
  exists pre-1.0.
- **Spline cutters** — explicitly deferred; would require new sketch/
  spline model entities not present anywhere today.
- **Viewport gizmo** — explicitly deferred; numeric entry only, matching
  envelope/current split UX.
- **GUI wiring** — included in this pass per user decision, scoped to
  Treeview + fixed-field editor, no new dialog/widget infrastructure.
