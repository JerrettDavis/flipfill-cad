from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


_exit_status = 0


def pytest_sessionfinish(session, exitstatus: int) -> None:
    # Recorded, not acted on, here: pytest's terminal reporter prints the
    # FAILURES section and final summary line from its own
    # pytest_sessionfinish hookimpl, and hook call order across plugins
    # (even with trylast) is not guaranteed to run after it. Stash the
    # real exit status and act in pytest_unconfigure instead, which fires
    # once everyone -- including the terminal reporter -- is done.
    global _exit_status
    _exit_status = int(exitstatus)


@pytest.hookimpl(trylast=True)
def pytest_unconfigure(config) -> None:
    """Exit the process immediately once pytest has finished reporting.

    The OpenCascade bindings (cadquery/OCP) that the test suite imports
    crash the interpreter with a native access violation during Python's
    own finalization on some platform/Python combinations — after every
    test has already run and pytest has already printed a correct summary.
    That corrupts the process exit code CI relies on. Terminating here
    skips the unreliable native teardown entirely.
    """

    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(_exit_status)
