"""mutmut's process isolation is chosen per platform by the gate (ADR-1122).

mutation_check.sh rewrites `process_isolation` from ci_mutation_scope.py, so the line
must exist in pyproject.toml and hold a value mutmut 3.8.1 accepts. With "fork" on
Linux mutants hung in torch autograd until they timed out (#877, #878); with
"forkserver" on macOS the stats run aborts in torch MPS.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from mutmut.configuration import ProcessIsolation

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def test_pyproject_declares_the_line_the_gate_rewrites():
    config = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["tool"]["mutmut"]
    assert ProcessIsolation(config["process_isolation"]) is ProcessIsolation.FORKSERVER
