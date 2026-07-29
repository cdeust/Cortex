"""Every listed module must import first in a fresh interpreter.

A circular import between two modules A and B is invisible to a normal test
run: whichever of the two pytest happens to import first pulls the other in
as a side effect, so by the time any test body runs, both are in
``sys.modules`` and every later import is a cache hit. The failure only
appears when the *cycle-completing* module is the first one imported — which
is what a consumer that imports it directly does, and what every test here
reproduces by launching a **separate interpreter per module**.

An in-process ``importlib.import_module`` would NOT reproduce it (issue #233:
``synaptic_plasticity_hebbian`` and ``synaptic_plasticity_stochastic`` both
raised ``ImportError`` on a fresh interpreter while the whole suite was
green). The subprocess is the point of this file, not an implementation
detail.

Add a module name to ``CYCLE_PRONE_MODULES`` whenever an import cycle is
broken anywhere in the tree; this file is the single home for that check.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]

CYCLE_PRONE_MODULES = [
    # issue #233 — synaptic plasticity: facade + leaf + two implementations
    "mcp_server.core.synaptic_plasticity",
    "mcp_server.core.synaptic_plasticity_stp",
    "mcp_server.core.synaptic_plasticity_hebbian",
    "mcp_server.core.synaptic_plasticity_stochastic",
]


@pytest.mark.parametrize("module_name", CYCLE_PRONE_MODULES)
def test_module_imports_first_in_a_fresh_interpreter(module_name: str) -> None:
    """Importing the module as the very first project import must succeed."""
    result = subprocess.run(
        [sys.executable, "-c", f"import {module_name}"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, (
        f"`import {module_name}` failed in a fresh interpreter "
        f"(exit {result.returncode}).\nstdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
    assert result.stderr == "", (
        f"`import {module_name}` wrote to stderr in a fresh interpreter:\n"
        f"{result.stderr}"
    )
