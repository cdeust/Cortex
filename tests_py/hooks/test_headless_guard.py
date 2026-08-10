"""Tests for the headless-authoring hook guard.

Validates:
  (a) ``is_headless_authoring_child`` reflects the env flag;
  (b) ``exit_if_headless_authoring_child`` exits 0 in the child, no-ops else;
  (c) integration: a real hook invoked as ``python -m`` short-circuits BEFORE
      doing any work when the flag is set (proven by the absence of the
      stderr log line the hook emits on its normal no-stdin path), and still
      runs normally without the flag.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest


def test_is_headless_authoring_child_reads_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_server.hooks import _headless_guard as g

    monkeypatch.delenv("CORTEX_HEADLESS_AUTHORING_CHILD", raising=False)
    assert g.is_headless_authoring_child() is False

    monkeypatch.setenv("CORTEX_HEADLESS_AUTHORING_CHILD", "1")
    assert g.is_headless_authoring_child() is True

    # Any value other than exactly "1" is NOT a child (defensive).
    monkeypatch.setenv("CORTEX_HEADLESS_AUTHORING_CHILD", "0")
    assert g.is_headless_authoring_child() is False


def test_exit_if_child_raises_systemexit_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_server.hooks import _headless_guard as g

    monkeypatch.setenv("CORTEX_HEADLESS_AUTHORING_CHILD", "1")
    with pytest.raises(SystemExit) as exc:
        g.exit_if_headless_authoring_child()
    assert exc.value.code == 0


def test_exit_if_child_noops_outside_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mcp_server.hooks import _headless_guard as g

    monkeypatch.delenv("CORTEX_HEADLESS_AUTHORING_CHILD", raising=False)
    # Must NOT raise.
    g.exit_if_headless_authoring_child()


def _run_hook(flag: str | None) -> subprocess.CompletedProcess[str]:
    """Run session_lifecycle as ``python -m`` with empty stdin.

    No local `timeout=` (issue #402): a fixed wall-clock bound makes the
    verdict depend on machine load, not on the guard's contract. A
    genuine hang is still caught by pytest's own global watchdog
    (`pyproject.toml` `timeout = 300`) -- process-wide (`os._exit(1)` on
    expiry, not a clean per-test failure; see `tests_py/benchmarks/
    test_lib_init_no_psycopg.py`'s module docstring for the full
    mechanism and its source).
    """
    env = dict(os.environ)
    if flag is None:
        env.pop("CORTEX_HEADLESS_AUTHORING_CHILD", None)
    else:
        env["CORTEX_HEADLESS_AUTHORING_CHILD"] = flag
    return subprocess.run(
        [sys.executable, "-m", "mcp_server.hooks.session_lifecycle"],
        input="",  # empty stdin → normal path logs "Empty stdin, exiting"
        capture_output=True,
        text=True,
        env=env,
    )


def test_guard_short_circuits_hook_before_work() -> None:
    """With the flag set, the hook exits 0 BEFORE its first stderr log line."""
    res = _run_hook(flag="1")
    assert res.returncode == 0
    # main() never runs, so the no-stdin log line is absent.
    assert "[methodology-hook]" not in res.stderr


def test_hook_runs_normally_without_flag() -> None:
    """Without the flag, the same invocation reaches main() and logs."""
    res = _run_hook(flag=None)
    assert res.returncode == 0
    # main() ran its no-stdin branch — the guard is what suppresses this above.
    assert "[methodology-hook]" in res.stderr
