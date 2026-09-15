"""Regression cover for the 2026-09-16 CLAUDE.md silent-fallback finding:
benchmarks/lib/ablation_runner.py sets CORTEX_ABLATE_<NAME>=1 in-process
and calls a benchmark's run_benchmark() directly, never importing
mcp_server/__main__.py or tests_py/conftest.py. Before this fix,
core/environment.read_environment_variable silently returned None when
unconfigured, so every ablation run measured the un-ablated system.

Runs in a bare subprocess (no pytest, no tests_py/conftest.py) to prove
the fix holds on the real ablation_runner entry path, not merely inside
the already-wired pytest session.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _run(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
    )


def test_ablation_runner_import_wires_the_seam_and_disables_the_mechanism():
    """The exact path benchmarks/lib/ablation_runner.py exercises:
    import it (which imports benchmarks.lib._composition_root_wiring for
    its side effect), set CORTEX_ABLATE_<NAME>=1 via its own
    _set_ablation_env helper, and prove is_mechanism_disabled sees it."""
    script = """
import benchmarks.lib.ablation_runner as runner
from mcp_server.core.ablation import Mechanism, is_mechanism_disabled

assert is_mechanism_disabled(Mechanism.ADAPTIVE_DECAY) is False, (
    "precondition: nothing set CORTEX_ABLATE_ADAPTIVE_DECAY yet"
)
saved = runner._set_ablation_env(Mechanism.ADAPTIVE_DECAY)
try:
    assert is_mechanism_disabled(Mechanism.ADAPTIVE_DECAY) is True, (
        "ablation_runner set CORTEX_ABLATE_ADAPTIVE_DECAY=1 but the "
        "mechanism still reads as enabled -- the composition-root seam "
        "did not wire, so this ablation run would silently measure the "
        "un-ablated system"
    )
finally:
    runner._restore_env(saved)
print("OK")
"""
    result = _run(script)
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_unconfigured_reader_raises_instead_of_silently_treating_flags_as_unset():
    """A bare script that reaches core/ablation.py WITHOUT importing any
    composition root (mcp_server/__main__.py, scripts/launcher.py,
    tests_py/conftest.py, or a benchmarks/lib bootstrap) must fail
    loudly, not silently report every mechanism as enabled."""
    script = """
from mcp_server.core.ablation import Mechanism, is_mechanism_disabled
try:
    is_mechanism_disabled(Mechanism.ADAPTIVE_DECAY)
    print("NO_RAISE")
except RuntimeError as exc:
    msg = str(exc)
    assert "not configured" in msg or "configure_core_environment_reader" in msg
    print("RAISED")
"""
    result = _run(script)
    assert result.returncode == 0, result.stderr
    assert "RAISED" in result.stdout, result.stdout
