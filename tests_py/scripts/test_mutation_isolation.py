"""mutmut forks each mutant from a fork server, not from the suite (ADR-1122).

With mutmut's default ``fork`` isolation every mutant is forked from the process that
already ran the suite; on the Linux runner it then hangs in torch autograd until
mutmut times it out, and a timeout fails the gate (#877, #878).
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from mutmut.configuration import ProcessIsolation

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def test_mutmut_forks_mutants_from_a_clean_fork_server():
    config = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["tool"]["mutmut"]
    isolation = ProcessIsolation(config["process_isolation"])
    assert isolation is ProcessIsolation.FORKSERVER
