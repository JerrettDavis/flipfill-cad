from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def pytest_sessionfinish(session, exitstatus: int) -> None:
    """Exit the process immediately once pytest has reported its results.

    The OpenCascade bindings (cadquery/OCP) that the test suite imports
    crash the interpreter with a native access violation during Python's
    own finalization on some platform/Python combinations — after every
    test has already run and pytest has already printed a correct summary.
    That corrupts the process exit code CI relies on. Terminating here,
    right after pytest has decided ``exitstatus``, skips the unreliable
    native teardown entirely.
    """

    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(exitstatus)
