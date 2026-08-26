# Slice/Cut Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single two-body axis-aligned `SplitSpec` with an ordered, named, N-body slicer (`SlicingSpec`) whose cuts are either arbitrarily-oriented planes or existing scene objects used as cutting solids, wired through the model, generation engine, commands layer, CLI, desktop GUI, the shipped example, and a new Gherkin/`pytest-bdd` end-to-end scenario.

**Architecture:** `Project.slicing: SlicingSpec` holds an ordered `list[SliceSpec]`. `flipfill.geometry.generator.slice_result` folds sequentially over the generated body: each slice produces a "piece" knife (what gets isolated as a named body) and a "remainder" knife (what gets removed going forward — identical to the piece knife for object cutters, offset by half the kerf `gap` for plane cutters), via `intersect`/`cut`. `flipfill.commands` gains list-management functions (`add_slice`/`remove_slice`/`reorder_slice`/`configure_slicing`) following the file's existing `CommandError`-raising, side-effect-only conventions. The CLI gets a `flipfill slice` subcommand group; the desktop UI gets a Treeview-based list editor replacing the old four-field split panel.

**Tech Stack:** Python 3.11+, CadQuery/OpenCascade (`cq.Shape.intersect`/`.cut`), numpy (unused directly in this feature — no new geometry math beyond what `flipfill.geometry.transforms` already provides), Tk/`ttk` for the desktop UI, `pytest` + new `pytest-bdd` dependency for the BDD scenario.

**Spec:** `docs/superpowers/specs/2026-08-25-slice-tool-design.md`

## Global Constraints

- This is a **breaking project-format change** — `Project.split`/`SplitSpec`/`SplitAxis` are removed outright, not deprecated. No schema-version bump (matches every other additive field change in this codebase; see spec).
- No spline/sketch-curve cutting surfaces in this pass (out of scope — see spec).
- No viewport plane gizmo — all cutter positioning is numeric entry, matching the existing envelope panel's style.
- Every new/changed public function in `commands.py` raises `CommandError` for user-facing problems and performs no console I/O, matching every existing function in that file.
- Every CLI subcommand supports `--json` and returns a nonzero exit code on failure, matching every existing command.
- Tests generate real OpenCascade solids and execute real Booleans — nothing is mocked, matching every existing test in this repo.
- `ruff check src tests examples` must stay clean (existing `[tool.ruff.lint]` config in `pyproject.toml`: `select = ["E", "F", "I", "UP", "B", "SIM", "RUF"]`, `ignore = ["E501", "RUF001"]`).
- Because of the OCP/cadquery interpreter-shutdown crash (ADR-006), never run `pytest`/`flipfill` in a way that bypasses `tests/conftest.py`'s `pytest_unconfigure` / `flipfill.cli.run()`'s `os._exit()` — always invoke `pytest` or `flipfill` normally (not by importing `main()`/`cli.py` internals into a throwaway script) so those hooks run.

---

## Task 1: Data model — `SliceCutterKind`, `SliceSpec`, `SlicingSpec`

**Files:**
- Modify: `src/flipfill/model.py`
- Modify: `src/flipfill/__init__.py`
- Test: `tests/test_model.py`

**Interfaces:**
- Produces: `flipfill.model.SliceCutterKind` (`StrEnum`: `PLANE = "plane"`, `OBJECT = "object"`), `flipfill.model.SliceSpec` (fields: `name: str`, `cutter_kind: SliceCutterKind`, `transform: Transform`, `gap: float`, `object_id: str | None`, methods `to_dict()`/`from_dict()`), `flipfill.model.SlicingSpec` (fields: `enabled: bool`, `slices: list[SliceSpec]`, `remainder_name: str`, methods `to_dict()`/`from_dict()`), `Project.slicing: SlicingSpec`.
- Removes: `flipfill.model.SplitAxis`, `flipfill.model.SplitSpec`, `Project.split`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_model.py` (add `SliceCutterKind`, `SliceSpec` to the existing import block from `flipfill.model`):

```python
def test_slicing_round_trip() -> None:
    project = Project(name="Slicing round trip")
    project.slicing.enabled = True
    project.slicing.remainder_name = "Rear Shell"
    project.slicing.slices.append(
        SliceSpec(
            name="Front Bezel",
            cutter_kind=SliceCutterKind.PLANE,
            transform=Transform(Vector3(0, 0, 8), Vector3(0, 0, 0)),
            gap=0.3,
        )
    )
    project.slicing.slices.append(
        SliceSpec(
            name="Battery Pocket",
            cutter_kind=SliceCutterKind.OBJECT,
            object_id="some-object-id",
        )
    )

    restored = Project.from_dict(project.to_dict())

    assert restored.to_dict() == project.to_dict()
    assert restored.slicing.enabled is True
    assert restored.slicing.remainder_name == "Rear Shell"
    assert restored.slicing.slices[0].cutter_kind is SliceCutterKind.PLANE
    assert restored.slicing.slices[0].transform.translation == Vector3(0, 0, 8)
    assert restored.slicing.slices[0].gap == 0.3
    assert restored.slicing.slices[1].cutter_kind is SliceCutterKind.OBJECT
    assert restored.slicing.slices[1].object_id == "some-object-id"


def test_slicing_defaults_to_disabled_with_no_slices() -> None:
    project = Project()
    assert project.slicing.enabled is False
    assert project.slicing.slices == []
    assert project.slicing.remainder_name == "Remainder"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_model.py -v`
Expected: FAIL — `ImportError: cannot import name 'SliceCutterKind' from 'flipfill.model'` (or `AttributeError: SliceSpec`), since these don't exist yet.

- [ ] **Step 3: Remove `SplitAxis`/`SplitSpec`, add the new types**

In `src/flipfill/model.py`, replace the `SplitAxis` enum (currently right after `GeometryKind`):

```python
class SplitAxis(StrEnum):
    X = "x"
    Y = "y"
    Z = "z"
```

with:

```python
class SliceCutterKind(StrEnum):
    """How a SliceSpec's cutting tool is defined."""

    PLANE = "plane"
    OBJECT = "object"
```

Replace the `SplitSpec` dataclass (currently after `EnvelopeSpec`, before `Project`):

```python
@dataclass(slots=True)
class SplitSpec:
    enabled: bool = False
    axis: SplitAxis = SplitAxis.Z
    offset: float = 0.0
    gap: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": bool(self.enabled),
            "axis": self.axis.value,
            "offset": float(self.offset),
            "gap": float(self.gap),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> SplitSpec:
        value = value or {}
        return cls(
            enabled=bool(value.get("enabled", False)),
            axis=SplitAxis(value.get("axis", SplitAxis.Z.value)),
            offset=float(value.get("offset", 0.0)),
            gap=float(value.get("gap", 0.0)),
        )
```

with:

```python
@dataclass(slots=True)
class SliceSpec:
    """One ordered cut. A plane cutter carves off everything on its local
    -Z side (named ``name``); local +Z continues to the next cut or
    becomes the slicing remainder. An object cutter uses an existing
    SceneObject's resolved solid as the cutting tool instead."""

    name: str = "Body"
    cutter_kind: SliceCutterKind = SliceCutterKind.PLANE
    transform: Transform = field(default_factory=Transform)
    gap: float = 0.0
    object_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "cutter_kind": self.cutter_kind.value,
            "transform": self.transform.to_dict(),
            "gap": float(self.gap),
            "object_id": self.object_id,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> SliceSpec:
        return cls(
            name=str(value.get("name", "Body")),
            cutter_kind=SliceCutterKind(
                value.get("cutter_kind", SliceCutterKind.PLANE.value)
            ),
            transform=Transform.from_dict(value.get("transform")),
            gap=float(value.get("gap", 0.0)),
            object_id=value.get("object_id"),
        )


@dataclass(slots=True)
class SlicingSpec:
    """An ordered list of cuts applied to the generated body, producing
    ``len(slices) + 1`` named bodies (the last named ``remainder_name``)."""

    enabled: bool = False
    slices: list[SliceSpec] = field(default_factory=list)
    remainder_name: str = "Remainder"

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": bool(self.enabled),
            "slices": [s.to_dict() for s in self.slices],
            "remainder_name": self.remainder_name,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> SlicingSpec:
        value = value or {}
        return cls(
            enabled=bool(value.get("enabled", False)),
            slices=[SliceSpec.from_dict(v) for v in value.get("slices", [])],
            remainder_name=str(value.get("remainder_name", "Remainder")),
        )
```

In the `Project` dataclass, replace:

```python
    split: SplitSpec = field(default_factory=SplitSpec)
```

with:

```python
    slicing: SlicingSpec = field(default_factory=SlicingSpec)
```

In `Project.to_dict`, replace `"split": self.split.to_dict(),` with `"slicing": self.slicing.to_dict(),`.

In `Project.from_dict`, replace `split=SplitSpec.from_dict(value.get("split")),` with `slicing=SlicingSpec.from_dict(value.get("slicing")),`.

`src/flipfill/__init__.py` re-exports `SplitAxis` in its public API (it does not re-export `SplitSpec`). Replace:

```python
from .model import (
    ClearanceMode,
    EnvelopeSpec,
    ObjectRole,
    PrimitiveKind,
    Project,
    SceneObject,
    SplitAxis,
    Transform,
    Vector3,
)

__all__ = [
    "ClearanceMode",
    "EnvelopeSpec",
    "ObjectRole",
    "PrimitiveKind",
    "Project",
    "SceneObject",
    "SplitAxis",
    "Transform",
    "Vector3",
]
```

with:

```python
from .model import (
    ClearanceMode,
    EnvelopeSpec,
    ObjectRole,
    PrimitiveKind,
    Project,
    SceneObject,
    SliceCutterKind,
    SliceSpec,
    SlicingSpec,
    Transform,
    Vector3,
)

__all__ = [
    "ClearanceMode",
    "EnvelopeSpec",
    "ObjectRole",
    "PrimitiveKind",
    "Project",
    "SceneObject",
    "SliceCutterKind",
    "SliceSpec",
    "SlicingSpec",
    "Transform",
    "Vector3",
]
```

- [ ] **Step 4: Update the test imports**

In `tests/test_model.py`, add `SliceCutterKind` and `SliceSpec` to the `from flipfill.model import (...)` block (keep everything else alphabetically sorted per ruff's `I` rule).

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_model.py -v`
Expected: PASS (all tests in this file, including the pre-existing `test_project_round_trip`).

- [ ] **Step 6: Commit**

```bash
git add src/flipfill/model.py src/flipfill/__init__.py tests/test_model.py
git commit -m "feat(model): replace SplitSpec with an ordered multi-cut SlicingSpec"
```

**Note for later tasks:** after this commit, `src/flipfill/geometry/generator.py`, `src/flipfill/cli.py`, `src/flipfill/ui/app.py`, and `examples/create_demo.py` all still import `SplitAxis`/reference `project.split` and will fail to import. `tests/test_generator.py`, `tests/test_cli.py`, `tests/test_e2e.py`, and `tests/test_golden.py` will fail to collect until Tasks 2, 3, and 5 fix those files respectively — this is expected and resolved by Task 8's full-suite verification.

---

## Task 2: Generation engine — plane/object knives and the slicing fold

**Files:**
- Modify: `src/flipfill/geometry/generator.py`
- Test: `tests/test_generator.py`

**Interfaces:**
- Consumes: `flipfill.model.SliceCutterKind`, `SliceSpec`, `SlicingSpec`, `Project.slicing` (Task 1). `flipfill.geometry.transforms.transform_shape(shape: cq.Shape, transform: Transform) -> cq.Shape` (existing). `flipfill.geometry.bounds.Bounds3D`, `bounds_from_shape` (existing). `flipfill.geometry.importers.GeometryRepository.resolve(scene_object: SceneObject) -> ResolvedGeometry` (existing).
- Produces: `flipfill.geometry.generator.slice_result(result: cq.Shape, slicing: SlicingSpec, repository: GeometryRepository, project: Project, tolerance: float, messages: list[GenerationMessage]) -> dict[str, cq.Shape]`. `GenerationResult.sliced_bodies: dict[str, cq.Shape]` (replaces `split_a`/`split_b`). `_boolean_step`'s third positional parameter is renamed `owner: SceneObject | SliceSpec` (was `scene_object: SceneObject`) — callers in later tasks pass either type positionally; behavior for `SceneObject` owners is unchanged.
- Removes: `flipfill.geometry.generator.split_shape`, `GenerationResult.split_a`, `GenerationResult.split_b`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_generator.py`, replace the `SplitAxis` import with `SliceCutterKind, SliceSpec` in the `from flipfill.model import (...)` block, and replace `test_split_produces_two_valid_halves` with:

```python
def test_plane_slice_reproduces_axis_split_with_gap() -> None:
    project = Project()
    project.envelope.kind = PrimitiveKind.BOX
    project.envelope.size = Vector3(20, 20, 20)
    project.slicing.enabled = True
    project.slicing.remainder_name = "Top"
    project.slicing.slices.append(
        SliceSpec(name="Bottom", cutter_kind=SliceCutterKind.PLANE, gap=0.4)
    )

    result = generate(project)

    assert set(result.sliced_bodies) == {"Bottom", "Top"}
    bottom = result.sliced_bodies["Bottom"]
    top = result.sliced_bodies["Top"]
    assert bottom.isValid() and top.isValid()
    assert bottom.Volume() + top.Volume() == pytest.approx(
        20 * 20 * 19.6, abs=1.0e-5
    )


def test_multi_slice_chain_partitions_whole_volume() -> None:
    project = Project()
    project.envelope.kind = PrimitiveKind.BOX
    project.envelope.size = Vector3(30, 30, 30)
    project.slicing.enabled = True
    project.slicing.slices.extend(
        [
            SliceSpec(
                name="Front Bezel",
                cutter_kind=SliceCutterKind.PLANE,
                transform=Transform(Vector3(0, 0, -5)),
            ),
            SliceSpec(
                name="Center Support",
                cutter_kind=SliceCutterKind.PLANE,
                transform=Transform(Vector3(0, 0, 5)),
            ),
        ]
    )

    result = generate(project)

    assert set(result.sliced_bodies) == {"Front Bezel", "Center Support", "Remainder"}
    for shape in result.sliced_bodies.values():
        assert shape.isValid()
        assert shape.Volume() > 0
    assert sum(shape.Volume() for shape in result.sliced_bodies.values()) == pytest.approx(
        30 * 30 * 30, rel=1.0e-6
    )


def test_object_cutter_slices_using_scene_object_solid() -> None:
    project = Project()
    project.envelope.kind = PrimitiveKind.BOX
    project.envelope.size = Vector3(20, 20, 20)
    knife = SceneObject(
        name="Knife",
        role=ObjectRole.REFERENCE,
        primitive=PrimitiveSpec(PrimitiveKind.BOX, Vector3(40, 40, 40)),
        transform=Transform(Vector3(0, 0, -20)),
    )
    project.objects.append(knife)
    project.slicing.enabled = True
    project.slicing.slices.append(
        SliceSpec(name="Bottom Half", cutter_kind=SliceCutterKind.OBJECT, object_id=knife.id)
    )

    result = generate(project)

    assert set(result.sliced_bodies) == {"Bottom Half", "Remainder"}
    bottom = result.sliced_bodies["Bottom Half"]
    remainder = result.sliced_bodies["Remainder"]
    assert bottom.isValid() and remainder.isValid()
    assert bottom.Volume() == pytest.approx(20 * 20 * 10, rel=1.0e-3)
    assert remainder.Volume() == pytest.approx(20 * 20 * 10, rel=1.0e-3)


def test_slice_with_missing_object_id_raises() -> None:
    project = Project()
    project.envelope.kind = PrimitiveKind.BOX
    project.envelope.size = Vector3(20, 20, 20)
    project.slicing.enabled = True
    project.slicing.slices.append(
        SliceSpec(name="Bad", cutter_kind=SliceCutterKind.OBJECT, object_id="does-not-exist")
    )

    with pytest.raises(GenerationError):
        generate(project)


def test_slice_referencing_mesh_only_object_raises(tmp_path: Path) -> None:
    import cadquery as cq
    from cadquery import exporters

    mesh_path = tmp_path / "knife.stl"
    exporters.export(cq.Workplane("XY").box(40, 40, 40), str(mesh_path))

    project = Project()
    project.envelope.kind = PrimitiveKind.BOX
    project.envelope.size = Vector3(20, 20, 20)
    knife = SceneObject(name="Mesh Knife", role=ObjectRole.REFERENCE, source_path=str(mesh_path))
    project.objects.append(knife)
    project.slicing.enabled = True
    project.slicing.slices.append(
        SliceSpec(name="Bad", cutter_kind=SliceCutterKind.OBJECT, object_id=knife.id)
    )

    with pytest.raises(GenerationError):
        generate(project)
```

Check whether `Path` is already imported at the top of `tests/test_generator.py` (for the `tmp_path: Path` type hint) — if not, add `from pathlib import Path`.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_generator.py -v`
Expected: FAIL — `AttributeError: 'SplitSpec' object has no attribute ...` / `ImportError` for `SliceCutterKind`, since `generator.py` still uses the old model and `SliceCutterKind`/`SliceSpec` aren't imported yet in the test file (this also confirms Task 1's model changes broke `generator.py`, as noted).

- [ ] **Step 3: Implement the slicing engine**

In `src/flipfill/geometry/generator.py`:

Replace the import line:

```python
from flipfill.geometry.bounds import Bounds3D, bounds_from_shape, obb_from_vertices
```

with (add `transform_shape`):

```python
from flipfill.geometry.bounds import Bounds3D, bounds_from_shape, obb_from_vertices
from flipfill.geometry.transforms import transform_shape
```

Replace the `flipfill.model` import block's `SplitAxis` with `SliceCutterKind, SliceSpec, SlicingSpec`:

```python
from flipfill.model import (
    ClearanceMode,
    ObjectRole,
    PrimitiveKind,
    PrimitiveSpec,
    Project,
    SceneObject,
    SliceCutterKind,
    SliceSpec,
    SlicingSpec,
    Transform,
    Vector3,
)
```

Replace `GenerationResult`'s `split_a`/`split_b` fields:

```python
    split_a: cq.Shape | None = None
    split_b: cq.Shape | None = None
```

with:

```python
    sliced_bodies: dict[str, cq.Shape] = field(default_factory=dict)
```

Replace the `_boolean_step` function's signature and body (generalizing `scene_object: SceneObject` to `owner: SceneObject | SliceSpec`, and factoring the label/id lookups into two small helpers placed just above it):

```python
def _owner_label(owner: SceneObject | SliceSpec) -> str:
    if isinstance(owner, SceneObject):
        return f"'{owner.name}' ({owner.role.value})"
    return f"slice '{owner.name}'"


def _owner_id(owner: SceneObject | SliceSpec) -> str | None:
    return owner.id if isinstance(owner, SceneObject) else None


def _boolean_step(
    op: str,
    result: cq.Shape,
    shape: cq.Shape,
    owner: SceneObject | SliceSpec,
    tolerance: float,
    messages: list[GenerationMessage],
) -> cq.Shape:
    """Apply one fuse/cut/intersect step, retrying once after a topology
    cleanup pass.

    OCCT Booleans can fail on otherwise-valid inputs because of small
    numerical artifacts (sliver faces, duplicate edges) in one operand.
    Retrying with both sides ``.clean()``-ed first recovers a real fraction
    of those failures; when it doesn't, the resulting error names the
    specific object/slice responsible instead of a generic "Boolean
    generation failed", so a user knows what to fix.
    """

    method = getattr(result, op)
    try:
        return method(shape, tol=tolerance)
    except Exception as first_exc:
        try:
            cleaned_result = result.clean()
            cleaned_shape = shape.clean()
            recovered = getattr(cleaned_result, op)(cleaned_shape, tol=tolerance)
        except Exception as exc:
            raise GenerationError(
                f"{op.capitalize()} failed while combining {_owner_label(owner)}: {exc}"
            ) from exc
        messages.append(
            GenerationMessage(
                MessageLevel.WARNING,
                f"{op.capitalize()} with {_owner_label(owner)} needed a topology cleanup "
                f"pass to succeed ({first_exc}); the result may warrant a closer look.",
                _owner_id(owner),
            )
        )
        return recovered
```

(This changes the parameter name only; `_fuse_many`/`_cut_many` call it positionally and need no changes. The generated warning/error text for existing `SceneObject` owners is byte-for-byte identical to before.)

Add these new functions directly below `_cut_many` (before `def generate(...)`):

```python
def _local_box(size_x: float, size_y: float, z_min: float, z_max: float) -> cq.Shape:
    """A box spanning [-size_x/2, size_x/2] x [-size_y/2, size_y/2] x
    [z_min, z_max] in local coordinates, ready to be positioned by a
    Transform via transform_shape -- used to build a knife whose local
    z=0 plane is the cutter's own plane, before it is rotated/translated
    into world space."""
    size_z = z_max - z_min
    box = cq.Workplane("XY").box(size_x, size_y, size_z, centered=True).val()
    return box.translate((0.0, 0.0, (z_min + z_max) / 2.0))


def _plane_knives(
    transform: Transform, gap: float, bounds: Bounds3D
) -> tuple[cq.Shape, cq.Shape]:
    """Two knife solids for one plane cut: the first isolates the piece
    carved off (local -Z side), the second is what gets removed from the
    remainder going forward. They differ only when ``gap`` (kerf) is
    nonzero, matching the ``low_plane``/``high_plane`` split of the
    now-removed ``split_shape``, generalized from a world axis to an
    arbitrary oriented plane."""

    padding = max(bounds.size.x, bounds.size.y, bounds.size.z, 1.0) + 10.0
    half_gap = max(0.0, gap) / 2.0
    size_xy = 2.0 * padding
    piece_knife = _local_box(size_xy, size_xy, -padding, -half_gap)
    remainder_knife = _local_box(size_xy, size_xy, -padding, half_gap)
    return transform_shape(piece_knife, transform), transform_shape(remainder_knife, transform)


def _object_knife(
    slice_spec: SliceSpec, repository: GeometryRepository, project: Project
) -> cq.Shape:
    if not slice_spec.object_id:
        raise GenerationError(f"Slice '{slice_spec.name}' has no object reference")
    scene_object = project.object_by_id(slice_spec.object_id)
    if scene_object is None:
        raise GenerationError(
            f"Slice '{slice_spec.name}' references a missing object id "
            f"{slice_spec.object_id!r}"
        )
    resolved = repository.resolve(scene_object)
    if resolved.brep is None:
        raise GenerationError(
            f"Slice '{slice_spec.name}' references '{scene_object.name}', which has no "
            "BRep geometry; mesh-only objects cannot be used as a cutting tool."
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
            piece_knife, remainder_knife = _plane_knives(
                slice_spec.transform, slice_spec.gap, bounds
            )
        else:
            piece_knife = remainder_knife = _object_knife(slice_spec, repository, project)
        piece = _boolean_step(
            "intersect", remainder, piece_knife, slice_spec, tolerance, messages
        )
        remainder = _boolean_step(
            "cut", remainder, remainder_knife, slice_spec, tolerance, messages
        )
        if piece.isNull() or piece.Volume() <= tolerance:
            raise GenerationError(f"Slice '{slice_spec.name}' produced an empty body")
        bodies[slice_spec.name] = piece.clean()
    if remainder.isNull() or remainder.Volume() <= tolerance:
        raise GenerationError("Slicing consumed the entire body; the remainder is empty")
    bodies[slicing.remainder_name] = remainder.clean()
    return bodies
```

In `generate(...)`, replace the split block:

```python
    if project.split.enabled:
        try:
            generated.split_a, generated.split_b = split_shape(
                generated.result,
                project.split.axis,
                project.split.offset,
                project.split.gap,
                project.boolean_tolerance,
            )
        except Exception as exc:
            generated.messages.append(
                GenerationMessage(MessageLevel.ERROR, f"Split operation failed: {exc}")
            )
```

with:

```python
    if project.slicing.enabled:
        generated.sliced_bodies = slice_result(
            generated.result,
            project.slicing,
            repository,
            project,
            project.boolean_tolerance,
            generated.messages,
        )
```

(Note: unlike the old split block, this does **not** swallow exceptions into a message — a `GenerationError` from `slice_result` propagates out of `generate()`, matching how every other fatal Boolean failure in this function already propagates via `GenerationError`, e.g. the "Boolean generation produced a null shape" check above it. The `test_slice_with_missing_object_id_raises`/`test_slice_referencing_mesh_only_object_raises` tests above assert exactly this.)

Delete the entire `split_shape` function (the last function in the file, `def split_shape(...) -> tuple[cq.Shape, cq.Shape]: ...`).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_generator.py -v`
Expected: PASS — all tests in this file, including the pre-existing ones untouched by this change (envelope fit, clearance modes, occupant overlap, etc).

- [ ] **Step 5: Commit**

```bash
git add src/flipfill/geometry/generator.py tests/test_generator.py
git commit -m "feat(generator): replace split_shape with an N-body slicing fold"
```

---

## Task 3: Commands + CLI — `flipfill slice` command group

**Files:**
- Modify: `src/flipfill/commands.py`
- Modify: `src/flipfill/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `SliceCutterKind`, `SliceSpec` (Task 1); `commands.find_object(project: Project, ref: str) -> SceneObject` (existing, raises `CommandError`); `commands.CommandError` (existing).
- Produces: `commands.configure_slicing(project, *, enabled=None, remainder_name=None) -> None`; `commands.add_slice(project, *, name, cutter_kind, transform=None, gap=0.0, object_id=None, index=None) -> SliceSpec`; `commands.remove_slice(project, name_or_index: str) -> None`; `commands.reorder_slice(project, name_or_index: str, new_index: int) -> None`; `commands.list_slices(project) -> list[SliceSpec]`. CLI: `flipfill slice <project> add|remove|move|list|enable|disable|remainder-name`.
- Removes: `commands.configure_split`, CLI `split` subcommand, `--split-dir` (renamed `--slice-dir`).

- [ ] **Step 1: Write the failing tests**

In `tests/test_cli.py`, replace `test_split_configure` with:

```python
def test_slice_add_plane_and_list(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    project_path = tmp_path / "demo.flipfill.json"
    main(["new", str(project_path)])
    capsys.readouterr()

    code = main(
        [
            "slice",
            str(project_path),
            "add",
            "--name",
            "Front Bezel",
            "--plane",
            "--at-z",
            "8",
            "--gap",
            "0.3",
        ]
    )
    assert code == 0
    capsys.readouterr()

    assert main(["slice", str(project_path), "list", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["slices"]) == 1
    assert payload["slices"][0]["name"] == "Front Bezel"
    assert payload["slices"][0]["cutter_kind"] == "plane"
    assert payload["slices"][0]["gap"] == pytest.approx(0.3)

    project = load_project(project_path)
    assert project.slicing.slices[0].transform.translation.z == pytest.approx(8.0)


def test_slice_add_object_cutter(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    project_path = tmp_path / "demo.flipfill.json"
    main(["new", str(project_path)])
    main(
        [
            "blocker",
            str(project_path),
            "--role",
            "additive",
            "--kind",
            "box",
            "--name",
            "Knife",
            "--size",
            "40",
            "40",
            "40",
        ]
    )
    capsys.readouterr()

    code = main(
        ["slice", str(project_path), "add", "--name", "Battery Pocket", "--object", "Knife"]
    )
    assert code == 0

    project = load_project(project_path)
    assert project.slicing.slices[0].cutter_kind.value == "object"
    knife = project.object_by_id(project.slicing.slices[0].object_id)
    assert knife is not None and knife.name == "Knife"


def test_slice_remove_move_and_toggle(tmp_path: Path) -> None:
    project_path = tmp_path / "demo.flipfill.json"
    main(["new", str(project_path)])
    main(["slice", str(project_path), "add", "--name", "A", "--plane", "--at-z", "1"])
    main(["slice", str(project_path), "add", "--name", "B", "--plane", "--at-z", "2"])

    assert main(["slice", str(project_path), "move", "B", "--to", "0"]) == 0
    project = load_project(project_path)
    assert [s.name for s in project.slicing.slices] == ["B", "A"]

    assert main(["slice", str(project_path), "remove", "A"]) == 0
    project = load_project(project_path)
    assert [s.name for s in project.slicing.slices] == ["B"]

    assert main(["slice", str(project_path), "enable"]) == 0
    assert load_project(project_path).slicing.enabled is True
    assert main(["slice", str(project_path), "disable"]) == 0
    assert load_project(project_path).slicing.enabled is False

    assert main(["slice", str(project_path), "remainder-name", "Rear Shell"]) == 0
    assert load_project(project_path).slicing.remainder_name == "Rear Shell"


def test_slice_add_rejects_duplicate_name(tmp_path: Path) -> None:
    project_path = tmp_path / "demo.flipfill.json"
    main(["new", str(project_path)])
    assert main(["slice", str(project_path), "add", "--name", "A", "--plane"]) == 0

    code = main(["slice", str(project_path), "add", "--name", "A", "--plane"])

    assert code != 0


def test_slice_add_object_cutter_rejects_gap(tmp_path: Path) -> None:
    project_path = tmp_path / "demo.flipfill.json"
    main(["new", str(project_path)])
    main(
        [
            "blocker",
            str(project_path),
            "--role",
            "additive",
            "--kind",
            "box",
            "--name",
            "Knife",
            "--size",
            "10",
            "10",
            "10",
        ]
    )

    code = main(
        [
            "slice",
            str(project_path),
            "add",
            "--name",
            "A",
            "--object",
            "Knife",
            "--gap",
            "0.5",
        ]
    )

    assert code != 0


def test_slice_remove_unknown_fails(tmp_path: Path) -> None:
    project_path = tmp_path / "demo.flipfill.json"
    main(["new", str(project_path)])

    assert main(["slice", str(project_path), "remove", "Nope"]) != 0
```

Also update `test_generate_validate_and_export` and any other test in `tests/test_cli.py` that references `--split-dir`/`split_a`/`split_b`/`project.split` — search the file for `split` (case-insensitive) and update each occurrence to the `slice`-based equivalent following the patterns in Task 5 below (there is exactly one such test besides the removed `test_split_configure`; confirm by re-reading the file after Task 1/2 land, since `git grep -n split tests/test_cli.py` is authoritative).

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cli.py -v`
Expected: FAIL — collection error (`cli.py` still imports `SplitAxis`, which no longer exists) and/or `argparse` errors for the unrecognized `slice` subcommand.

- [ ] **Step 3: Implement `commands.py` changes**

In `src/flipfill/commands.py`, add the import of the new model types (extend whatever `from flipfill.model import (...)` block already exists with `SliceCutterKind, SliceSpec`), then replace `configure_split`:

```python
def configure_split(
    project: Project,
    enabled: bool | None = None,
    axis: SplitAxis | None = None,
    offset: float | None = None,
    gap: float | None = None,
) -> None:
    split = project.split
    if enabled is not None:
        split.enabled = enabled
    if axis is not None:
        split.axis = axis
    if offset is not None:
        split.offset = offset
    if gap is not None:
        if gap < 0:
            raise CommandError("Split gap must be zero or positive")
        split.gap = gap
```

with:

```python
def configure_slicing(
    project: Project,
    enabled: bool | None = None,
    remainder_name: str | None = None,
) -> None:
    slicing = project.slicing
    if enabled is not None:
        slicing.enabled = enabled
    if remainder_name is not None:
        name = remainder_name.strip()
        if not name:
            raise CommandError("Remainder name must not be empty")
        if any(s.name == name for s in slicing.slices):
            raise CommandError(
                f"Remainder name {name!r} collides with an existing slice name"
            )
        slicing.remainder_name = name


def _validate_slice_name(
    project: Project, name: str, *, ignore_index: int | None = None
) -> str:
    name = name.strip()
    if not name:
        raise CommandError("Slice name must not be empty")
    if name == project.slicing.remainder_name:
        raise CommandError(f"Slice name {name!r} collides with the remainder name")
    for index, existing in enumerate(project.slicing.slices):
        if index == ignore_index:
            continue
        if existing.name == name:
            raise CommandError(f"A slice named {name!r} already exists")
    return name


def add_slice(
    project: Project,
    name: str,
    cutter_kind: SliceCutterKind,
    transform: Transform | None = None,
    gap: float = 0.0,
    object_id: str | None = None,
    index: int | None = None,
) -> SliceSpec:
    validated_name = _validate_slice_name(project, name)
    if gap < 0:
        raise CommandError("Slice gap must be zero or positive")

    if cutter_kind is SliceCutterKind.OBJECT:
        if gap != 0:
            raise CommandError("Gap only applies to plane cutters")
        if not object_id:
            raise CommandError("An object cutter requires an object id or name")
        resolved_object = find_object(project, object_id)
        slice_spec = SliceSpec(
            name=validated_name, cutter_kind=cutter_kind, object_id=resolved_object.id
        )
    else:
        slice_spec = SliceSpec(
            name=validated_name,
            cutter_kind=cutter_kind,
            transform=transform or Transform(),
            gap=gap,
        )

    slices = project.slicing.slices
    if index is None or index >= len(slices):
        slices.append(slice_spec)
    else:
        slices.insert(max(0, index), slice_spec)
    return slice_spec


def _find_slice_index(project: Project, name_or_index: str) -> int:
    slices = project.slicing.slices
    try:
        index = int(name_or_index)
    except (TypeError, ValueError):
        index = None
    if index is not None:
        if 0 <= index < len(slices):
            return index
        raise CommandError(f"No slice at index {index}")
    for position, slice_spec in enumerate(slices):
        if slice_spec.name == name_or_index:
            return position
    raise CommandError(f"No slice named {name_or_index!r}")


def remove_slice(project: Project, name_or_index: str) -> None:
    index = _find_slice_index(project, name_or_index)
    del project.slicing.slices[index]


def reorder_slice(project: Project, name_or_index: str, new_index: int) -> None:
    slices = project.slicing.slices
    index = _find_slice_index(project, name_or_index)
    slice_spec = slices.pop(index)
    slices.insert(max(0, min(new_index, len(slices))), slice_spec)


def list_slices(project: Project) -> list[SliceSpec]:
    return list(project.slicing.slices)
```

- [ ] **Step 4: Implement `cli.py` changes**

In `src/flipfill/cli.py`:

Replace the model import line:

```python
from flipfill.model import ClearanceMode, ObjectRole, PrimitiveKind, SplitAxis, Vector3
```

with:

```python
from flipfill.model import ClearanceMode, ObjectRole, PrimitiveKind, SliceCutterKind, Transform, Vector3
```

Update the module docstring's two mentions of `split` (near the top of the file) to `slice`, e.g. `"...generate, validate, split, export, render..."` → `"...generate, validate, slice, export, render..."` and `` "``role``, ``clearance``, ``blocker``, ``envelope``, ``split``) load a" `` → `` "``role``, ``clearance``, ``blocker``, ``envelope``, ``slice``) load a" ``.

Add a slug helper near the other private helpers (e.g. right after `_vector_arg`):

```python
def _slugify(name: str) -> str:
    slug = "".join(c.lower() if c.isalnum() else "_" for c in name).strip("_")
    return slug or "body"
```

Replace the entire `command_split` function and its section header:

```python
# ----------------------------------------------------------------------
# split
# ----------------------------------------------------------------------


def command_split(args: argparse.Namespace) -> int:
    project = _load(args.project)
    enabled = True if args.enable else (False if args.disable else None)
    try:
        commands.configure_split(
            project,
            enabled=enabled,
            axis=SplitAxis(args.axis) if args.axis else None,
            offset=args.offset,
            gap=args.gap,
        )
    except CommandError as exc:
        _die(str(exc))
    _save(project, args.project)
    split = project.split
    _emit(
        args,
        {"ok": True, "split": split.to_dict()},
        f"Split: enabled={split.enabled} axis={split.axis.value} "
        f"offset={split.offset} gap={split.gap}",
    )
    return 0
```

with:

```python
# ----------------------------------------------------------------------
# slice
# ----------------------------------------------------------------------


def _slice_to_dict(project, slice_spec) -> dict[str, Any]:
    data = slice_spec.to_dict()
    if slice_spec.object_id:
        target = project.object_by_id(slice_spec.object_id)
        data["object_name"] = target.name if target else None
    return data


def command_slice_add(args: argparse.Namespace) -> int:
    project = _load(args.project)
    cutter_kind = SliceCutterKind.OBJECT if args.object_ref else SliceCutterKind.PLANE
    transform = None
    if cutter_kind is SliceCutterKind.PLANE:
        transform = Transform(
            translation=Vector3(args.at_x, args.at_y, args.at_z),
            rotation_deg=Vector3(args.rotate_x, args.rotate_y, args.rotate_z),
        )
    try:
        slice_spec = commands.add_slice(
            project,
            name=args.name,
            cutter_kind=cutter_kind,
            transform=transform,
            gap=args.gap,
            object_id=args.object_ref,
            index=args.index,
        )
    except CommandError as exc:
        _die(str(exc))
    _save(project, args.project)
    _emit(
        args,
        {"ok": True, "slice": _slice_to_dict(project, slice_spec)},
        f"Added slice '{slice_spec.name}' ({slice_spec.cutter_kind.value})",
    )
    return 0


def command_slice_remove(args: argparse.Namespace) -> int:
    project = _load(args.project)
    try:
        commands.remove_slice(project, args.slice)
    except CommandError as exc:
        _die(str(exc))
    _save(project, args.project)
    _emit(args, {"ok": True}, f"Removed slice {args.slice!r}")
    return 0


def command_slice_move(args: argparse.Namespace) -> int:
    project = _load(args.project)
    try:
        commands.reorder_slice(project, args.slice, args.to_index)
    except CommandError as exc:
        _die(str(exc))
    _save(project, args.project)
    _emit(args, {"ok": True}, f"Moved slice {args.slice!r} to index {args.to_index}")
    return 0


def command_slice_list(args: argparse.Namespace) -> int:
    project = _load(args.project)
    slices = commands.list_slices(project)
    payload = [_slice_to_dict(project, s) for s in slices]
    lines = [f"{i}: {s.name} ({s.cutter_kind.value})" for i, s in enumerate(slices)] or [
        "(no slices configured)"
    ]
    _emit(args, {"ok": True, "slices": payload}, "\n".join(lines))
    return 0


def command_slice_enable(args: argparse.Namespace) -> int:
    project = _load(args.project)
    commands.configure_slicing(project, enabled=args.enabled)
    _save(project, args.project)
    _emit(
        args,
        {"ok": True, "enabled": project.slicing.enabled},
        f"Slicing {'enabled' if args.enabled else 'disabled'}",
    )
    return 0


def command_slice_remainder_name(args: argparse.Namespace) -> int:
    project = _load(args.project)
    try:
        commands.configure_slicing(project, remainder_name=args.name)
    except CommandError as exc:
        _die(str(exc))
    _save(project, args.project)
    _emit(
        args,
        {"ok": True, "remainder_name": project.slicing.remainder_name},
        f"Remainder name set to {args.name!r}",
    )
    return 0
```

In `command_generate`, replace:

```python
    if project.split.enabled and generated.split_a is not None and generated.split_b is not None:
        split_dir = Path(args.split_dir or Path(args.output).parent).resolve()
        split_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(args.output).stem
        first = export_shape(generated.split_a, split_dir / f"{stem}_A.step")
        second = export_shape(generated.split_b, split_dir / f"{stem}_B.step")
        outputs["split_a"] = str(first)
        outputs["split_b"] = str(second)
        if not getattr(args, "json", False):
            print(f"Exported split halves: {first}, {second}")
```

with:

```python
    if project.slicing.enabled and generated.sliced_bodies:
        slice_dir = Path(args.slice_dir or Path(args.output).parent).resolve()
        slice_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(args.output).stem
        slice_outputs: dict[str, str] = {}
        for name, shape in generated.sliced_bodies.items():
            exported = export_shape(shape, slice_dir / f"{stem}_{_slugify(name)}.step")
            slice_outputs[name] = str(exported)
        outputs["slices"] = slice_outputs
        if not getattr(args, "json", False):
            print("Exported sliced bodies: " + ", ".join(slice_outputs.values()))
```

In `command_export`'s `package` branch, replace:

```python
            if generated.split_a is not None and generated.split_b is not None:
                written["split_a"] = str(
                    export_shape(generated.split_a, output_dir / f"{stem}_A.step")
                )
                written["split_b"] = str(
                    export_shape(generated.split_b, output_dir / f"{stem}_B.step")
                )
```

with:

```python
            for name, shape in generated.sliced_bodies.items():
                written[f"slice:{name}"] = str(
                    export_shape(shape, output_dir / f"{stem}_{_slugify(name)}.step")
                )
```

In `build_parser()`, replace the `# split` block:

```python
    # split
    split = subparsers.add_parser("split", help="Configure the planar split")
    split.add_argument("project")
    group = split.add_mutually_exclusive_group()
    group.add_argument("--enable", action="store_true")
    group.add_argument("--disable", action="store_true")
    split.add_argument("--axis", choices=[a.value for a in SplitAxis])
    split.add_argument("--offset", type=float)
    split.add_argument("--gap", type=float)
    _add_json_flag(split)
    split.set_defaults(handler=command_split)
```

with:

```python
    # slice
    slice_parser = subparsers.add_parser("slice", help="Manage the ordered slice/cut list")
    slice_parser.add_argument("project")
    slice_sub = slice_parser.add_subparsers(dest="slice_command", required=True)

    slice_add = slice_sub.add_parser("add", help="Add a plane or object cutter slice")
    slice_add.add_argument("--name", required=True)
    cutter_group = slice_add.add_mutually_exclusive_group(required=True)
    cutter_group.add_argument("--plane", action="store_true")
    cutter_group.add_argument(
        "--object", dest="object_ref", help="Object id or name to use as the cutting solid"
    )
    slice_add.add_argument("--at-x", type=float, dest="at_x", default=0.0)
    slice_add.add_argument("--at-y", type=float, dest="at_y", default=0.0)
    slice_add.add_argument("--at-z", type=float, dest="at_z", default=0.0)
    slice_add.add_argument("--rotate-x", type=float, dest="rotate_x", default=0.0)
    slice_add.add_argument("--rotate-y", type=float, dest="rotate_y", default=0.0)
    slice_add.add_argument("--rotate-z", type=float, dest="rotate_z", default=0.0)
    slice_add.add_argument("--gap", type=float, default=0.0)
    slice_add.add_argument("--index", type=int, help="Insert position (default: append)")
    _add_json_flag(slice_add)
    slice_add.set_defaults(handler=command_slice_add)

    slice_remove = slice_sub.add_parser("remove", help="Remove a slice by name or index")
    slice_remove.add_argument("slice", help="Slice name or index")
    _add_json_flag(slice_remove)
    slice_remove.set_defaults(handler=command_slice_remove)

    slice_move = slice_sub.add_parser("move", help="Reorder a slice")
    slice_move.add_argument("slice", help="Slice name or index")
    slice_move.add_argument("--to", type=int, required=True, dest="to_index")
    _add_json_flag(slice_move)
    slice_move.set_defaults(handler=command_slice_move)

    slice_list = slice_sub.add_parser("list", help="List configured slices")
    _add_json_flag(slice_list)
    slice_list.set_defaults(handler=command_slice_list)

    slice_enable = slice_sub.add_parser("enable", help="Enable slicing")
    _add_json_flag(slice_enable)
    slice_enable.set_defaults(handler=command_slice_enable, enabled=True)

    slice_disable = slice_sub.add_parser("disable", help="Disable slicing")
    _add_json_flag(slice_disable)
    slice_disable.set_defaults(handler=command_slice_enable, enabled=False)

    slice_remainder = slice_sub.add_parser(
        "remainder-name", help="Set the name of the final (unsliced) piece"
    )
    slice_remainder.add_argument("name")
    _add_json_flag(slice_remainder)
    slice_remainder.set_defaults(handler=command_slice_remainder_name)
```

In the `# generate` parser block, replace `generate_parser.add_argument("--split-dir")` with `generate_parser.add_argument("--slice-dir")`.

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_cli.py -v`
Expected: PASS for every test in this file.

- [ ] **Step 6: Commit**

```bash
git add src/flipfill/commands.py src/flipfill/cli.py tests/test_cli.py
git commit -m "feat(cli): add the 'flipfill slice' command group, remove 'split'"
```

---

## Task 4: Desktop GUI — slice-list editor

**Files:**
- Modify: `src/flipfill/ui/app.py`

**Interfaces:**
- Consumes: `commands.add_slice`, `commands.remove_slice`, `commands.reorder_slice`, `commands.configure_slicing`, `commands.list_slices` (Task 3); `SliceCutterKind` (Task 1); `GenerationResult.sliced_bodies` (Task 2).
- Produces: no new public interface — this is a leaf UI change consumed by nothing else in this plan.

- [ ] **Step 1: Replace the split state/panel with a slice-list editor**

In `src/flipfill/ui/app.py`, this task is the first place the desktop UI calls into `flipfill.commands` — today it only imports `flipfill.geometry.*`/`flipfill.model` directly (see `docs/ARCHITECTURE.md`'s "Dependency direction" section, which already names this as the intended next step: "the desktop UI is the next one, closing the last GUI/CLI logic duplication"). Add the import, right after the existing `from flipfill.geometry.importers import GeometryRepository` line:

```python
from flipfill import commands
from flipfill.commands import CommandError
```

Replace `SplitAxis` in the `from flipfill.model import (...)` block with `SliceCutterKind`.

Replace the split state initialization inside `_build_generate_tab` (currently):

```python
        self.split_enabled = tk.BooleanVar(value=False)
        self.split_axis = tk.StringVar(value=SplitAxis.Z.value)
        self.split_offset = tk.StringVar(value="0")
        self.split_gap = tk.StringVar(value="0")

        ttk.Label(parent, text="Output split", style="Section.TLabel").grid(
            row=0, column=0, columnspan=2, sticky=tk.W
        )
        ttk.Checkbutton(parent, text="Generate two halves", variable=self.split_enabled).grid(
            row=1, column=0, columnspan=2, sticky=tk.W, pady=3
        )
        ttk.Label(parent, text="Axis").grid(row=2, column=0, sticky=tk.W, pady=2)
        ttk.Combobox(
            parent,
            textvariable=self.split_axis,
            values=[axis.value for axis in SplitAxis],
            state="readonly",
            width=8,
        ).grid(row=2, column=1, sticky=tk.W, pady=2)
        self._entry_row(parent, 3, "Plane offset", self.split_offset)
        self._entry_row(parent, 4, "Separation gap", self.split_gap)

        buttons = ttk.Frame(parent)
        buttons.grid(row=5, column=0, columnspan=2, sticky=tk.EW, pady=(10, 4))
```

with:

```python
        self.slicing_enabled = tk.BooleanVar(value=False)
        self.slice_remainder_name = tk.StringVar(value="Remainder")
        self.slice_name = tk.StringVar(value="")
        self.slice_cutter_kind = tk.StringVar(value=SliceCutterKind.PLANE.value)
        self.slice_object_ref = tk.StringVar(value="")
        self.slice_x = tk.StringVar(value="0")
        self.slice_y = tk.StringVar(value="0")
        self.slice_z = tk.StringVar(value="0")
        self.slice_rx = tk.StringVar(value="0")
        self.slice_ry = tk.StringVar(value="0")
        self.slice_rz = tk.StringVar(value="0")
        self.slice_gap = tk.StringVar(value="0")

        ttk.Label(parent, text="Slices", style="Section.TLabel").grid(
            row=0, column=0, columnspan=2, sticky=tk.W
        )
        ttk.Checkbutton(
            parent, text="Enable slicing on generate", variable=self.slicing_enabled
        ).grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=3)

        self.slice_tree = ttk.Treeview(
            parent,
            columns=("name", "kind", "summary"),
            show="headings",
            height=5,
            selectmode="browse",
        )
        self.slice_tree.heading("name", text="Name")
        self.slice_tree.heading("kind", text="Cutter")
        self.slice_tree.heading("summary", text="Summary")
        self.slice_tree.column("name", width=110)
        self.slice_tree.column("kind", width=60)
        self.slice_tree.column("summary", width=140)
        self.slice_tree.grid(row=2, column=0, columnspan=2, sticky=tk.NSEW, pady=(4, 4))
        self.slice_tree.bind("<<TreeviewSelect>>", self._slice_tree_selected)

        list_buttons = ttk.Frame(parent)
        list_buttons.grid(row=3, column=0, columnspan=2, sticky=tk.EW)
        ttk.Button(list_buttons, text="Add", command=self.add_slice_row).pack(side=tk.LEFT)
        ttk.Button(list_buttons, text="Remove", command=self.remove_slice_row).pack(
            side=tk.LEFT, padx=4
        )
        ttk.Button(list_buttons, text="Move Up", command=lambda: self.move_slice_row(-1)).pack(
            side=tk.LEFT
        )
        ttk.Button(list_buttons, text="Move Down", command=lambda: self.move_slice_row(1)).pack(
            side=tk.LEFT, padx=4
        )

        editor = ttk.Frame(parent)
        editor.grid(row=4, column=0, columnspan=2, sticky=tk.EW, pady=(8, 0))
        editor.columnconfigure(1, weight=1)
        self._entry_row(editor, 0, "Name", self.slice_name)
        ttk.Label(editor, text="Cutter").grid(row=1, column=0, sticky=tk.W, padx=(0, 6), pady=2)
        ttk.Combobox(
            editor,
            textvariable=self.slice_cutter_kind,
            values=[kind.value for kind in SliceCutterKind],
            state="readonly",
            width=10,
        ).grid(row=1, column=1, sticky=tk.W, pady=2)
        self._entry_row(editor, 2, "Object (id or name)", self.slice_object_ref)
        self._entry_row(editor, 3, "Plane X", self.slice_x)
        self._entry_row(editor, 4, "Plane Y", self.slice_y)
        self._entry_row(editor, 5, "Plane Z", self.slice_z)
        self._entry_row(editor, 6, "Plane rotate X", self.slice_rx)
        self._entry_row(editor, 7, "Plane rotate Y", self.slice_ry)
        self._entry_row(editor, 8, "Plane rotate Z", self.slice_rz)
        self._entry_row(editor, 9, "Kerf gap", self.slice_gap)
        ttk.Button(editor, text="Apply Row", command=self.apply_slice_row).grid(
            row=10, column=0, columnspan=2, sticky=tk.W, pady=(6, 0)
        )

        ttk.Label(parent, text="Remainder name").grid(row=5, column=0, sticky=tk.W, pady=(8, 2))
        ttk.Entry(parent, textvariable=self.slice_remainder_name).grid(
            row=5, column=1, sticky=tk.EW, pady=(8, 2)
        )

        buttons = ttk.Frame(parent)
        buttons.grid(row=6, column=0, columnspan=2, sticky=tk.EW, pady=(10, 4))
```

The new block above already places its own `buttons` frame at `row=6` (one more than the old panel's `row=5`, since the new content occupies one additional row: label, checkbutton, tree, list-buttons, editor, remainder-name, buttons = 7 rows vs. the old label, checkbutton, axis, offset, gap, buttons = 6 rows). Exactly one row lower, `_build_generate_tab` immediately after the `buttons` block has:

```python
        ttk.Label(parent, text="Generation report", style="Section.TLabel").grid(
            row=6, column=0, columnspan=2, sticky=tk.W, pady=(8, 3)
        )
```

Change this one `row=6` to `row=7`. Nothing else below it needs to change: `log_frame` is already at `row=8` with a deliberately unused `row=7` gap in the original layout (and `parent.rowconfigure(8, weight=1)` at the top of the method already targets `log_frame`'s row), so the shift exactly absorbs into that existing gap with no further renumbering needed.

- [ ] **Step 2: Wire the list editor's behavior**

Replace `_apply_split_controls` with:

```python
    def _slice_tree_selected(self, _event=None) -> None:
        selection = self.slice_tree.selection()
        if not selection:
            return
        index = int(selection[0])
        slice_spec = self.project.slicing.slices[index]
        self.slice_name.set(slice_spec.name)
        self.slice_cutter_kind.set(slice_spec.cutter_kind.value)
        self.slice_object_ref.set(slice_spec.object_id or "")
        self.slice_x.set(str(slice_spec.transform.translation.x))
        self.slice_y.set(str(slice_spec.transform.translation.y))
        self.slice_z.set(str(slice_spec.transform.translation.z))
        self.slice_rx.set(str(slice_spec.transform.rotation_deg.x))
        self.slice_ry.set(str(slice_spec.transform.rotation_deg.y))
        self.slice_rz.set(str(slice_spec.transform.rotation_deg.z))
        self.slice_gap.set(str(slice_spec.gap))

    def refresh_slice_tree(self) -> None:
        self.slice_tree.delete(*self.slice_tree.get_children())
        for index, slice_spec in enumerate(self.project.slicing.slices):
            if slice_spec.cutter_kind is SliceCutterKind.PLANE:
                summary = (
                    f"z={slice_spec.transform.translation.z:.2f} gap={slice_spec.gap:.2f}"
                )
            else:
                target = self.project.object_by_id(slice_spec.object_id or "")
                summary = f"object: {target.name if target else slice_spec.object_id}"
            self.slice_tree.insert(
                "", tk.END, iid=str(index),
                values=(slice_spec.name, slice_spec.cutter_kind.value, summary),
            )

    def add_slice_row(self, index: int | None = None) -> None:
        try:
            commands.add_slice(
                self.project,
                name=self.slice_name.get() or f"Slice {len(self.project.slicing.slices) + 1}",
                cutter_kind=SliceCutterKind(self.slice_cutter_kind.get()),
                transform=Transform(
                    translation=Vector3(
                        self._float(self.slice_x, "Plane X"),
                        self._float(self.slice_y, "Plane Y"),
                        self._float(self.slice_z, "Plane Z"),
                    ),
                    rotation_deg=Vector3(
                        self._float(self.slice_rx, "Plane rotate X"),
                        self._float(self.slice_ry, "Plane rotate Y"),
                        self._float(self.slice_rz, "Plane rotate Z"),
                    ),
                ),
                gap=max(0.0, self._float(self.slice_gap, "Kerf gap")),
                object_id=self.slice_object_ref.get() or None,
                index=index,
            )
        except (CommandError, ValueError) as exc:
            messagebox.showerror("Invalid slice", str(exc), parent=self.root)
            return
        self._mark_dirty()
        self._invalidate_generation()
        self.refresh_slice_tree()

    def remove_slice_row(self) -> None:
        selection = self.slice_tree.selection()
        if not selection:
            return
        index = int(selection[0])
        commands.remove_slice(self.project, self.project.slicing.slices[index].name)
        self._mark_dirty()
        self._invalidate_generation()
        self.refresh_slice_tree()

    def move_slice_row(self, offset: int) -> None:
        selection = self.slice_tree.selection()
        if not selection:
            return
        index = int(selection[0])
        name = self.project.slicing.slices[index].name
        commands.reorder_slice(self.project, name, index + offset)
        self._mark_dirty()
        self._invalidate_generation()
        self.refresh_slice_tree()
        new_index = next(
            i for i, s in enumerate(self.project.slicing.slices) if s.name == name
        )
        self.slice_tree.selection_set(str(new_index))

    def apply_slice_row(self) -> None:
        selection = self.slice_tree.selection()
        if not selection:
            self.add_slice_row()
            return
        index = int(selection[0])
        name = self.project.slicing.slices[index].name
        commands.remove_slice(self.project, name)
        self.add_slice_row(index=index)

    def _apply_slicing_controls(self) -> None:
        commands.configure_slicing(
            self.project,
            enabled=bool(self.slicing_enabled.get()),
            remainder_name=self.slice_remainder_name.get() or None,
        )
```

Update `_apply_current_panel_if_possible`'s `elif current == 2:` branch from `self._apply_split_controls()` to `self._apply_slicing_controls()`.

Update `generate_model`'s `self._apply_split_controls()` call to `self._apply_slicing_controls()`, and after `self.generated = generated` add `self.refresh_slice_tree()` (so an edited-then-generated project's tree reflects `configure_slicing`'s side effects, e.g. a cleared/normalized remainder name).

Replace `_display_generation_report`'s split-volume block:

```python
        if generated.split_a is not None and generated.split_b is not None:
            self._write_log(
                f"\nSplit A volume: {generated.split_a.Volume():.3f} mm³\n"
                f"Split B volume: {generated.split_b.Volume():.3f} mm³\n",
                "info",
            )
```

with:

```python
        if generated.sliced_bodies:
            lines = "".join(
                f"{name} volume: {shape.Volume():.3f} mm³\n"
                for name, shape in generated.sliced_bodies.items()
            )
            self._write_log(f"\n{lines}", "info")
```

Replace the export-package split lines:

```python
        export_shape(generated.split_a, output / f"{safe_name}_A.step")
        export_shape(generated.split_b, output / f"{safe_name}_B.step")
```

with:

```python
        for name, shape in generated.sliced_bodies.items():
            export_shape(shape, output / f"{safe_name}_{self._slugify_body_name(name)}.step")
```

Add a small static helper near `_slugify`-style helpers (or as a `@staticmethod` near `_float`):

```python
    @staticmethod
    def _slugify_body_name(name: str) -> str:
        slug = "".join(c.lower() if c.isalnum() else "_" for c in name).strip("_")
        return slug or "body"
```

Replace:

```python
    def _load_split_controls(self) -> None:
        self.split_enabled.set(self.project.split.enabled)
        self.split_axis.set(self.project.split.axis.value)
        self.split_offset.set(f"{self.project.split.offset:g}")
        self.split_gap.set(f"{self.project.split.gap:g}")

    def _sync_all_controls(self) -> None:
        self._load_envelope_controls()
        self._load_split_controls()
```

with:

```python
    def _load_slicing_controls(self) -> None:
        self.slicing_enabled.set(self.project.slicing.enabled)
        self.slice_remainder_name.set(self.project.slicing.remainder_name)
        self.slice_name.set("")
        self.slice_cutter_kind.set(SliceCutterKind.PLANE.value)
        self.slice_object_ref.set("")
        for var in (
            self.slice_x, self.slice_y, self.slice_z,
            self.slice_rx, self.slice_ry, self.slice_rz, self.slice_gap,
        ):
            var.set("0")
        self.refresh_slice_tree()

    def _sync_all_controls(self) -> None:
        self._load_envelope_controls()
        self._load_slicing_controls()
```

- [ ] **Step 3: Verify the GUI still starts and behaves correctly**

There is no automated Tk interaction test in this repo today (`docs/TEST_PLAN.md` explicitly lists this as an open gap — CI only checks that the process starts under Xvfb). Use the `run` skill to launch the app and manually verify, per the "UI changes" rule in this project's engineering guidelines:

1. `python -m flipfill gui` (or `./scripts/run.ps1`) with no project argument.
2. Add an occupant primitive (existing blocker flow), fit the envelope.
3. On the Generate tab, add a plane slice (name "Top", z=2, gap=0.3) and an object slice (referencing the occupant by name), enable slicing, click Generate.
4. Confirm the report lists a volume line per named body, the slice tree shows both rows with correct summaries, Move Up/Down reorders correctly, Remove deletes the selected row, and Export Package writes one STEP file per body plus the fit-check/project files.
5. Take a screenshot (existing `flipfill render` / doc-screenshot tooling) if useful for later documentation, but this is not required for this task's completion.

Run `python -m flipfill doctor` first if anything fails to rule out an environment issue unrelated to this change.

- [ ] **Step 4: Commit**

```bash
git add src/flipfill/ui/app.py
git commit -m "feat(ui): replace the split panel with a slice-list editor"
```

---

## Task 5: Example regeneration + golden/e2e test updates

**Files:**
- Modify: `examples/create_demo.py`
- Modify: `examples/portable_monitor_demo.flipfill.json` (regenerated, not hand-edited)
- Modify: `examples/portable_monitor_demo.step`, `examples/portable_monitor_demo_fitcheck.step` (regenerated binary/text artifacts)
- Delete: `examples/portable_monitor_demo_A.step`, `examples/portable_monitor_demo_B.step`
- Create: `examples/portable_monitor_demo_bottom.step`, `examples/portable_monitor_demo_top.step` (or whatever slugs the chosen slice names produce — see Step 1)
- Modify: `tests/test_golden.py`
- Modify: `tests/test_e2e.py`

**Interfaces:**
- Consumes: everything from Tasks 1-3 (`SliceCutterKind`, `SliceSpec`, `commands.add_slice`, `GenerationResult.sliced_bodies`, CLI `slice` subcommand).
- Produces: nothing consumed elsewhere in this plan — this is the last piece needed before the full-repo tests in Task 8 can pass.

- [ ] **Step 1: Update `examples/create_demo.py`**

Replace the `SplitAxis` import with `SliceCutterKind`, `SliceSpec` in the `from flipfill.model import (...)` block.

Replace:

```python
    repository = GeometryRepository()
    fit_envelope_to_objects(project, repository)
    project.split.enabled = True
    project.split.axis = SplitAxis.Z
    project.split.offset = 1.5
    project.split.gap = 0.35
    return project
```

with:

```python
    repository = GeometryRepository()
    fit_envelope_to_objects(project, repository)
    project.slicing.enabled = True
    project.slicing.slices.append(
        SliceSpec(
            name="Bottom Shell",
            cutter_kind=SliceCutterKind.PLANE,
            transform=Transform(translation=Vector3(0, 0, 1.5)),
            gap=0.35,
        )
    )
    project.slicing.remainder_name = "Top Shell"
    return project
```

Replace `main()`'s split export block:

```python
    if result.split_a is not None and result.split_b is not None:
        export_shape(result.split_a, ROOT / "portable_monitor_demo_A.step")
        export_shape(result.split_b, ROOT / "portable_monitor_demo_B.step")
```

with:

```python
    for name, shape in result.sliced_bodies.items():
        slug = "".join(c.lower() if c.isalnum() else "_" for c in name).strip("_")
        export_shape(shape, ROOT / f"portable_monitor_demo_{slug}.step")
```

- [ ] **Step 2: Regenerate the example artifacts**

Run: `python examples/create_demo.py`
Expected: prints the project path, the generated volume, and any messages; produces `examples/portable_monitor_demo.flipfill.json`, `examples/portable_monitor_demo.step`, `examples/portable_monitor_demo_fitcheck.step`, `examples/portable_monitor_demo_bottom_shell.step`, `examples/portable_monitor_demo_top_shell.step`. Note the exact volume printed for `result.result.Volume()` and the two new files' volumes (open them with a quick throwaway check, e.g. `python -c "from cadquery import importers; ..."`, or just trust the printed `GenerationMessage`s plus Step 3's test run) — you need these numbers for Step 3.

Delete the now-orphaned `examples/portable_monitor_demo_A.step` and `examples/portable_monitor_demo_B.step`:

```bash
git rm examples/portable_monitor_demo_A.step examples/portable_monitor_demo_B.step
```

- [ ] **Step 3: Update `tests/test_golden.py`**

Replace the constants and split-specific test:

```python
EXPECTED_VOLUME_MM3 = 64338.905
EXPECTED_SPLIT_A_MM3 = 14046.024
EXPECTED_SPLIT_B_MM3 = 49938.679
```

with (fill in the two slice volumes from the values `generate()` reports when you run the updated test the first time — this is a deterministic regeneration, not a guess: run `python -m pytest tests/test_golden.py::test_example_project_generates_cleanly -v` first to confirm `EXPECTED_VOLUME_MM3` still holds since envelope-fit inputs didn't change, then read the actual `Bottom Shell`/`Top Shell` volumes off a failing assertion's diff the first time you run the new test below and paste them in):

```python
EXPECTED_VOLUME_MM3 = 64338.905
EXPECTED_SLICE_BOTTOM_SHELL_MM3 = 14046.024  # placeholder -- replace with the value from the first failing run
EXPECTED_SLICE_TOP_SHELL_MM3 = 49938.679  # placeholder -- replace with the value from the first failing run
```

Replace `test_example_project_split_volumes_are_pinned`:

```python
def test_example_project_slice_volumes_are_pinned(generated) -> None:
    _, result = generated
    assert set(result.sliced_bodies) == {"Bottom Shell", "Top Shell"}
    bottom = result.sliced_bodies["Bottom Shell"]
    top = result.sliced_bodies["Top Shell"]
    assert bottom.Volume() == pytest.approx(EXPECTED_SLICE_BOTTOM_SHELL_MM3, rel=1.0e-3)
    assert top.Volume() == pytest.approx(EXPECTED_SLICE_TOP_SHELL_MM3, rel=1.0e-3)
    # The two pieces are strictly smaller than the whole body: the 0.35mm
    # kerf gap configured in this example removes a thin slab between them.
    assert bottom.Volume() + top.Volume() < result.result.Volume()
```

Update `test_example_project_loads_with_expected_shape`'s assertion `assert project.split.enabled is True` to `assert project.slicing.enabled is True`.

- [ ] **Step 4: Run the golden test, filling in the real pinned values**

Run: `python -m pytest tests/test_golden.py -v`

Expected first run: FAIL on the two `pytest.approx(EXPECTED_SLICE_..., rel=1.0e-3)` assertions, with the actual computed volumes shown in the assertion diff. Copy those exact numbers into `EXPECTED_SLICE_BOTTOM_SHELL_MM3`/`EXPECTED_SLICE_TOP_SHELL_MM3`, replacing the placeholders.

Run again: `python -m pytest tests/test_golden.py -v`
Expected: PASS for every test in this file.

- [ ] **Step 5: Update `tests/test_e2e.py`**

Replace step 6:

```python
    # 6. Enable a planar split down the middle.
    assert (
        main(
            ["split", str(project_path), "--enable", "--axis", "z", "--offset", "0", "--gap", "0.3"]
        )
        == 0
    )
```

with:

```python
    # 6. Add a plane slice and enable slicing.
    assert (
        main(
            [
                "slice",
                str(project_path),
                "add",
                "--name",
                "Bottom",
                "--plane",
                "--at-z",
                "0",
                "--gap",
                "0.3",
            ]
        )
        == 0
    )
    assert main(["slice", str(project_path), "enable"]) == 0
```

Replace step 8's split-dir/export block and the two `split_a`/`split_b` path variables:

```python
    # 8. Generate and export STEP, the fit-check assembly, and split halves.
    output = tmp_path / "out" / "case.step"
    fitcheck = tmp_path / "out" / "case_fitcheck.step"
    split_dir = tmp_path / "out"
    assert (
        main(
            [
                "generate",
                str(project_path),
                "-o",
                str(output),
                "--fitcheck",
                str(fitcheck),
                "--split-dir",
                str(split_dir),
            ]
        )
        == 0
    )
    assert output.exists() and output.stat().st_size > 0
    assert fitcheck.exists() and fitcheck.stat().st_size > 0
    split_a = split_dir / "case_A.step"
    split_b = split_dir / "case_B.step"
    assert split_a.exists() and split_a.stat().st_size > 0
    assert split_b.exists() and split_b.stat().st_size > 0
```

with:

```python
    # 8. Generate and export STEP, the fit-check assembly, and sliced bodies.
    output = tmp_path / "out" / "case.step"
    fitcheck = tmp_path / "out" / "case_fitcheck.step"
    slice_dir = tmp_path / "out"
    assert (
        main(
            [
                "generate",
                str(project_path),
                "-o",
                str(output),
                "--fitcheck",
                str(fitcheck),
                "--slice-dir",
                str(slice_dir),
            ]
        )
        == 0
    )
    assert output.exists() and output.stat().st_size > 0
    assert fitcheck.exists() and fitcheck.stat().st_size > 0
    slice_bottom = slice_dir / "case_bottom.step"
    slice_remainder = slice_dir / "case_remainder.step"
    assert slice_bottom.exists() and slice_bottom.stat().st_size > 0
    assert slice_remainder.exists() and slice_remainder.stat().st_size > 0
```

Update step 9's assertion `assert reloaded.split.enabled is True` to `assert reloaded.slicing.enabled is True`.

Update step 10's artifact tuple and volume comparison:

```python
    repository = GeometryRepository()
    for artifact in (output, fitcheck, split_a, split_b):
        resolved = repository.load(artifact)
        assert resolved.brep is not None
        assert resolved.brep.isValid()
        assert resolved.brep.Volume() > 0

    # The two split halves are strictly smaller than the whole body: the
    # configured 0.3mm split gap removes a thin slab between them.
    body = repository.load(output).brep
    half_a = repository.load(split_a).brep
    half_b = repository.load(split_b).brep
    assert 0 < half_a.Volume() + half_b.Volume() < body.Volume()
```

with:

```python
    repository = GeometryRepository()
    for artifact in (output, fitcheck, slice_bottom, slice_remainder):
        resolved = repository.load(artifact)
        assert resolved.brep is not None
        assert resolved.brep.isValid()
        assert resolved.brep.Volume() > 0

    # The two sliced pieces are strictly smaller than the whole body: the
    # configured 0.3mm kerf gap removes a thin slab between them.
    body = repository.load(output).brep
    bottom = repository.load(slice_bottom).brep
    remainder = repository.load(slice_remainder).brep
    assert 0 < bottom.Volume() + remainder.Volume() < body.Volume()
```

Update the module docstring's `"...optionally splits it, exports STEP..."` to `"...optionally slices it, exports STEP..."`.

- [ ] **Step 6: Run test to verify it passes**

Run: `python -m pytest tests/test_e2e.py tests/test_golden.py -v`
Expected: PASS for every test in both files.

- [ ] **Step 7: Commit**

```bash
git add examples/create_demo.py examples/portable_monitor_demo.flipfill.json \
  examples/portable_monitor_demo.step examples/portable_monitor_demo_fitcheck.step \
  examples/portable_monitor_demo_bottom_shell.step examples/portable_monitor_demo_top_shell.step \
  tests/test_golden.py tests/test_e2e.py
git commit -m "feat(examples): regenerate the demo project using the new slicer"
```

(The `git rm` for the old `_A.step`/`_B.step` files from Step 2 should already be staged; include it in this commit if it wasn't committed separately.)

---

## Task 6: BDD e2e scenario (`pytest-bdd`)

**Files:**
- Modify: `pyproject.toml`
- Create: `tests/features/slicing.feature`
- Create: `tests/test_slicing_bdd.py`

**Interfaces:**
- Consumes: `flipfill.commands` (`add_primitive_object`, `add_slice`, `configure_slicing`), `flipfill.geometry.generator` (`generate`, `fit_envelope_to_objects`), `flipfill.geometry.exporters.export_shape`, `flipfill.geometry.importers.GeometryRepository`, `flipfill.model` (`Project`, `SliceCutterKind`, `Transform`, `Vector3`, `PrimitiveKind`, `ObjectRole`, `ClearanceMode`) — all from Tasks 1-3, nothing new.
- Produces: nothing consumed elsewhere in this plan (terminal test artifact).

- [ ] **Step 1: Add the `pytest-bdd` dev dependency**

In `pyproject.toml`, add to `[project.optional-dependencies].dev`:

```toml
dev = [
  "pytest>=8,<10",
  "pytest-bdd>=7,<9",
  "pytest-cov>=6,<8",
  "ruff>=0.11,<1",
  "mypy>=1.15,<3",
  "pyinstaller>=6.13,<7",
]
```

Run: `python -m pip install -e ".[dev]"`
Expected: installs `pytest-bdd` and its dependencies into the active environment without error.

- [ ] **Step 2: Write the feature file**

Create `tests/features/slicing.feature`:

```gherkin
Feature: Slicing a generated body into multiple named parts

  Scenario: Slicing a case into front bezel, center support, and rear shell
    Given a new project with a rounded-box envelope sized like a handheld case
    And a screen, a battery, and mounting screws positioned inside it
    When the project is generated
    Then generation succeeds with no errors
    When I add a horizontal slice named "Front Bezel" near the front face
    And I add a horizontal slice named "Center Support" further back
    And the project is generated again with slicing enabled
    Then generation produces exactly 3 bodies
    And every produced body is a valid, positive-volume solid
    And the bodies are named "Front Bezel", "Center Support", and "Remainder"
    And every body's STEP export opens as a valid solid
```

- [ ] **Step 3: Write the failing step-definition module**

Create `tests/test_slicing_bdd.py`:

```python
"""BDD scenario for the slice/cut tool, driven through flipfill.commands
exactly like tests/test_e2e.py drives the CLI -- the same real, unmocked
OpenCascade pipeline, expressed as Gherkin per the project's test plan.
"""

from __future__ import annotations

from pathlib import Path

from pytest_bdd import given, parsers, scenarios, then, when

from flipfill import commands
from flipfill.geometry.exporters import export_shape
from flipfill.geometry.generator import fit_envelope_to_objects, generate
from flipfill.geometry.importers import GeometryRepository
from flipfill.model import (
    ClearanceMode,
    ObjectRole,
    PrimitiveKind,
    Project,
    SliceCutterKind,
    Transform,
    Vector3,
)

scenarios("features/slicing.feature")


@given(
    "a new project with a rounded-box envelope sized like a handheld case",
    target_fixture="ctx",
)
def _new_project(tmp_path: Path) -> dict:
    project = Project(name="BDD Case")
    project.envelope.kind = PrimitiveKind.ROUNDED_BOX
    project.envelope.radius = 6.0
    return {"project": project, "tmp_path": tmp_path, "repository": GeometryRepository()}


@given("a screen, a battery, and mounting screws positioned inside it")
def _add_occupants(ctx: dict) -> None:
    project: Project = ctx["project"]
    commands.add_primitive_object(
        project,
        role=ObjectRole.OCCUPANT,
        kind=PrimitiveKind.ROUNDED_BOX,
        size=Vector3(70.0, 110.0, 4.0),
        radius=2.0,
        translation=Vector3(0, 0, 6),
        name="Screen",
        clearance_mode=ClearanceMode.AABB,
        clearance_mm=0.5,
    )
    commands.add_primitive_object(
        project,
        role=ObjectRole.OCCUPANT,
        kind=PrimitiveKind.ROUNDED_BOX,
        size=Vector3(60.0, 90.0, 6.0),
        radius=2.0,
        translation=Vector3(0, 0, -6),
        name="Battery",
        clearance_mode=ClearanceMode.AABB,
        clearance_mm=0.5,
    )
    for x, y in [(-32, 58), (32, 58), (-32, -58), (32, -58)]:
        commands.add_primitive_object(
            project,
            role=ObjectRole.OCCUPANT,
            kind=PrimitiveKind.CYLINDER,
            size=Vector3(3.0, 3.0, 20.0),
            translation=Vector3(x, y, 0),
            name=f"Screw ({x}, {y})",
            clearance_mode=ClearanceMode.AABB,
            clearance_mm=0.2,
        )
    fit_envelope_to_objects(project, ctx["repository"])


@when("the project is generated")
def _generate_first(ctx: dict) -> None:
    ctx["generated"] = generate(ctx["project"], ctx["repository"])


@then("generation succeeds with no errors")
def _assert_no_errors(ctx: dict) -> None:
    assert ctx["generated"].errors == []


@when(parsers.parse('I add a horizontal slice named "{name}" near the front face'))
def _add_front_slice(ctx: dict, name: str) -> None:
    project: Project = ctx["project"]
    top_z = project.envelope.transform.translation.z + project.envelope.size.z / 2.0
    commands.add_slice(
        project,
        name=name,
        cutter_kind=SliceCutterKind.PLANE,
        transform=Transform(translation=Vector3(0, 0, top_z - 3.0)),
    )


@when(parsers.parse('I add a horizontal slice named "{name}" further back'))
def _add_second_slice(ctx: dict, name: str) -> None:
    project: Project = ctx["project"]
    top_z = project.envelope.transform.translation.z + project.envelope.size.z / 2.0
    commands.add_slice(
        project,
        name=name,
        cutter_kind=SliceCutterKind.PLANE,
        transform=Transform(translation=Vector3(0, 0, top_z - 10.0)),
    )


@when("the project is generated again with slicing enabled")
def _generate_second(ctx: dict) -> None:
    commands.configure_slicing(ctx["project"], enabled=True)
    ctx["generated"] = generate(ctx["project"], ctx["repository"])


@then(parsers.parse("generation produces exactly {count:d} bodies"))
def _assert_body_count(ctx: dict, count: int) -> None:
    assert len(ctx["generated"].sliced_bodies) == count


@then("every produced body is a valid, positive-volume solid")
def _assert_bodies_valid(ctx: dict) -> None:
    for shape in ctx["generated"].sliced_bodies.values():
        assert shape.isValid()
        assert shape.Volume() > 0


@then(parsers.parse('the bodies are named "{a}", "{b}", and "{c}"'))
def _assert_body_names(ctx: dict, a: str, b: str, c: str) -> None:
    assert set(ctx["generated"].sliced_bodies) == {a, b, c}


@then("every body's STEP export opens as a valid solid")
def _assert_export_round_trip(ctx: dict) -> None:
    repository = GeometryRepository()
    for index, (_name, shape) in enumerate(ctx["generated"].sliced_bodies.items()):
        path = ctx["tmp_path"] / f"body_{index}.step"
        export_shape(shape, path)
        resolved = repository.load(path)
        assert resolved.brep is not None
        assert resolved.brep.isValid()
        assert resolved.brep.Volume() > 0
```

- [ ] **Step 4: Run test to verify it fails, then passes**

Run: `python -m pytest tests/test_slicing_bdd.py -v`

If it fails, the most likely causes are: `pytest-bdd` not installed (re-run Step 1's install), a step-text mismatch between the `.feature` file and a `parsers.parse(...)`/plain-string step decorator (compare character-for-character, including punctuation and quotes), or a geometry issue (e.g. screws not fully contained by the fitted envelope, which would fail generation with a validation error rather than an exception — check `ctx["generated"].errors` if `test_no_errors`-equivalent assertions fail and adjust the screw Z placement/size if needed).

Expected once fixed: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml tests/features/slicing.feature tests/test_slicing_bdd.py
git commit -m "test: add a pytest-bdd end-to-end scenario for the slice tool"
```

---

## Task 7: Documentation updates

**Files:**
- Modify: `README.md`
- Modify: `docs/ARCHITECTURE.md`
- Modify: `docs/CAD_SEMANTICS.md`
- Modify: `docs/ROADMAP.md`
- Modify: `docs/PRODUCT_PLAN.md`
- Modify: `docs/TEST_PLAN.md`
- Modify: `docs/TECHNICAL_DECISIONS.md`
- Modify: `CHANGELOG.md`

**Interfaces:** none — documentation only, no code interfaces.

- [ ] **Step 1: `README.md`**

Replace the CLI quick-start example line:

```
flipfill split my_case.flipfill.json --enable --axis z --offset 1.5 --gap 0.35
```

with:

```
flipfill slice my_case.flipfill.json add --name "Bottom" --plane --at-z 1.5 --gap 0.35
flipfill slice my_case.flipfill.json enable
```

Replace the command reference table row:

```
| `split` | Configure the planar split applied during generate/export |
```

with:

```
| `slice` | Manage the ordered slice/cut list applied during generate/export |
```

In the numbered feature list near the top, replace `- Optionally splits the result along X, Y, or Z.` with `- Optionally slices the result into N named bodies along plane or object cutters.` and replace `optional split-half STEP files;` with `optional per-slice STEP files;`.

In "Important limitations in 0.1", replace the bullet about planar split (`- Planar split is implemented, but tongue-and-groove seams, ...`) with `- Slicing supports plane and object cutters; tongue-and-groove seams, screw bosses, heat-set insert placement, snap fits, and hinge generators are roadmap work. Spline/sketch-curve cutting surfaces and a viewport plane gizmo are also roadmap work (see docs/ROADMAP.md).`

- [ ] **Step 2: `docs/ARCHITECTURE.md`**

In the "Extensibility seams" list, add a new bullet after the clearance-strategies one:

```
- New slice cutter kinds can be added behind `SliceCutterKind`.
```

- [ ] **Step 3: `docs/CAD_SEMANTICS.md`**

Add a new section after "## Envelope" and before "## Generation order":

```markdown
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
```

Update "## Generation order" to mention slicing runs afterward:

```
base = envelope
positive = fuse(base, every additive)
result = cut(positive, every occupant cavity, every cutout blocker)
sliced_bodies = slice(result, every configured cut)  # when slicing is enabled
```

- [ ] **Step 4: `docs/ROADMAP.md`**

In the "Since 0.1: CLI completeness pass" section's bullet list, add:

```
- Replaced the single two-body axis-aligned `split` command with an
  ordered, named, N-body `slice` command: plane cutters (arbitrary
  position/orientation, optional kerf gap) or existing scene objects used
  as cutting solids. Wired through the CLI, `flipfill.commands`, the
  generation engine, the desktop UI, the shipped example, and a new
  `pytest-bdd` end-to-end scenario.
```

In "0.2: Mechanical assembly features", add (near the convex-hull/cable-sweep items):

```
- Spline/sketch-curve cutting surfaces for the slice tool (needs a new
  2D sketch/spline model entity that does not exist yet).
- A viewport plane gizmo for the slice tool (currently numeric entry
  only, matching the envelope panel).
```

- [ ] **Step 5: `docs/PRODUCT_PLAN.md`**

Replace `- Planar split.` (in the 0.1 feature list) with `- Ordered multi-body slicing (plane and object cutters).`

Replace both narrative mentions of `split it`/`split the shell` — in the opening paragraph, `..., produce internal cavities, add port and cable access, split the shell, and repeatedly inspect for collisions.` → `..., produce internal cavities, add port and cable access, slice the shell into named parts, and repeatedly inspect for collisions.` — and in "Success criteria", `..., generate a valid solid, split it, and import ...` → `..., generate a valid solid, slice it into named parts, and import ...`.

- [ ] **Step 6: `docs/TEST_PLAN.md`**

In "Current automated coverage", update the `test_generator.py` bullet's `"... planar split volume and validity, ..."` to `"... plane and object slice-cutter volume and validity, ..."`, and add a new bullet:

```
- a Gherkin/`pytest-bdd` end-to-end scenario for the slice tool
  (`tests/features/slicing.feature`, `tests/test_slicing_bdd.py`),
  driven through `flipfill.commands` exactly like `test_e2e.py` drives
  the CLI — no mocking.
```

In "Geometric regression strategy", replace `split-half volumes;` with `sliced-body volumes;`.

- [ ] **Step 7: `docs/TECHNICAL_DECISIONS.md`**

Add a new ADR after ADR-006:

```markdown
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
```

- [ ] **Step 8: `CHANGELOG.md`**

Add to the top of the "## Unreleased" section:

```markdown
- **Breaking:** replaced the single two-body axis-aligned `split` command
  and `Project.split` field with an ordered, named, N-body `slice`
  command and `Project.slicing` field. Cuts are plane cutters (arbitrary
  position/orientation, optional kerf gap) or existing scene objects used
  as cutting solids. Wired through the CLI, `flipfill.commands`, the
  generation engine (`GenerationResult.sliced_bodies` replaces
  `split_a`/`split_b`), the desktop UI, the shipped example, and a new
  `pytest-bdd` Gherkin end-to-end scenario (`tests/features/slicing.feature`).
```

- [ ] **Step 9: Commit**

```bash
git add README.md docs/ARCHITECTURE.md docs/CAD_SEMANTICS.md docs/ROADMAP.md \
  docs/PRODUCT_PLAN.md docs/TEST_PLAN.md docs/TECHNICAL_DECISIONS.md CHANGELOG.md
git commit -m "docs: document the slice/cut tool, replacing split references"
```

---

## Task 8: Full-repo verification

**Files:** none modified directly — this task only runs checks and fixes any stragglers it finds (most likely a leftover `split`/`SplitAxis`/`SplitSpec` reference somewhere not covered above).

- [ ] **Step 1: Search for any remaining reference to the removed API**

Run: `git grep -n "SplitAxis\|SplitSpec\|split_a\|split_b\|project\.split\|--split-dir\|command_split" -- ':!docs/superpowers'`

Expected: no output. If anything appears (e.g. a stray reference in a docstring, a script under `scripts/`, or `.github/workflows/*.yml`), fix it following the same pattern as the file it's found in and re-run this search until it's clean.

- [ ] **Step 2: Run the full test suite with coverage**

Run: `python -m pytest --cov=flipfill --cov-report=term-missing`
Expected: every test passes (0 failures, 0 errors, 0 collection errors). If any test outside this plan's scope references removed APIs indirectly (e.g. a fixture in `tests/conftest.py` — unlikely per Task 1's note, but verify), fix it.

- [ ] **Step 3: Run lint**

Run: `python -m ruff check src tests examples`
Expected: no findings. Pay particular attention to unused imports (`SplitAxis` removed from several files) and import ordering (`I` rule) in every file touched by this plan.

- [ ] **Step 4: Optional local mypy check**

Run: `mypy src/flipfill` (not wired into CI per `pyproject.toml`'s documented `casadi` stub issue — see ADR list — but useful local signal for the new `dict[str, cq.Shape]`/`SceneObject | SliceSpec` type usage introduced in this plan).
Expected: no new errors attributable to this change (pre-existing unrelated errors, if any, are out of scope).

- [ ] **Step 5: Manual doctor + fresh-clone-style sanity check**

Run: `python -m flipfill doctor`
Expected: all checks pass (cadquery/OCP/trimesh/VTK/Tk/off-screen-rendering healthy).

Run: `python -m flipfill slice examples/portable_monitor_demo.flipfill.json list --json`
Expected: JSON output listing the "Bottom Shell" slice added in Task 5, confirming the regenerated example project loads and the new CLI surface works end-to-end against a real project file.

- [ ] **Step 6: Final commit (only if Step 1-4 required fixes)**

```bash
git add -A
git commit -m "chore: fix stragglers found during slice-tool full-repo verification"
```

If no fixes were needed, skip this step — Task 7's commit is the last one, and the tree is already fully green.
