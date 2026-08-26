"""Deterministic regression test over the shipped example project.

Pins the generated volume of ``examples/portable_monitor_demo.flipfill.json``
so an unintentional change to the generation pipeline (offset math, Boolean
tolerance, envelope fitting, split geometry) shows up as a failing test
instead of silently shipping. Tolerances are loose enough to absorb harmless
floating-point noise between OpenCascade builds/platforms but tight enough to
catch a real regression.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from flipfill.geometry.generator import generate
from flipfill.geometry.importers import GeometryRepository
from flipfill.project_io import load_project

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "portable_monitor_demo.flipfill.json"

EXPECTED_VOLUME_MM3 = 64338.905
EXPECTED_SLICE_BOTTOM_SHELL_MM3 = 14046.024
EXPECTED_SLICE_TOP_SHELL_MM3 = 49938.679


@pytest.fixture(scope="module")
def generated():
    project = load_project(EXAMPLE)
    return project, generate(project, GeometryRepository())


def test_example_project_loads_with_expected_shape(generated) -> None:
    project, _ = generated
    assert project.name == "Portable Touch Monitor Demo"
    assert {o.name for o in project.objects} >= {
        "3.5in Display Module",
        "LiPo Battery",
        "Speaker",
        "Screen Opening",
    }
    assert project.slicing.enabled is True


def test_example_project_generates_cleanly(generated) -> None:
    _, result = generated
    errors = [m.message for m in result.messages if m.level.value == "error"]
    warnings = [m.message for m in result.messages if m.level.value == "warning"]
    assert errors == []
    assert warnings == []
    assert result.result.isValid()


def test_example_project_volume_is_pinned(generated) -> None:
    _, result = generated
    assert result.result.Volume() == pytest.approx(EXPECTED_VOLUME_MM3, rel=1.0e-3)


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
