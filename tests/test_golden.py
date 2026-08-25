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
EXPECTED_SPLIT_A_MM3 = 14046.024
EXPECTED_SPLIT_B_MM3 = 49938.679


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
    assert project.split.enabled is True


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


def test_example_project_split_volumes_are_pinned(generated) -> None:
    _, result = generated
    assert result.split_a is not None and result.split_b is not None
    assert result.split_a.Volume() == pytest.approx(EXPECTED_SPLIT_A_MM3, rel=1.0e-3)
    assert result.split_b.Volume() == pytest.approx(EXPECTED_SPLIT_B_MM3, rel=1.0e-3)
    # The two halves are strictly smaller than the whole body: the 0.35mm
    # split gap configured in this example removes a thin slab between them.
    assert result.split_a.Volume() + result.split_b.Volume() < result.result.Volume()
