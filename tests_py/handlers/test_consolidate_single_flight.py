"""One consolidation cycle at a time across processes (ADR-1112).

Measured 2026-10-21: two ``session_lifecycle --consolidate`` processes alive
at once for 1 h 26 and 2 h 50 on the owner's machine (experiment log entry
7). A second caller must skip, whether the holder is another process or this
one, and the kernel must release the lock when the holder dies.

Idea from commit 4dc9f66e (worktree fix-idle-tx-pileup).

source: ADR-1112
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

from mcp_server.infrastructure import consolidate_lock
from mcp_server.infrastructure.consolidate_lock import consolidate_single_flight

_REPO = Path(__file__).resolve().parents[2]
_HOLDER = """
import sys
from mcp_server.infrastructure.consolidate_lock import consolidate_single_flight
with consolidate_single_flight() as held:
    print("HELD" if held else "BUSY", flush=True)
    sys.stdin.readline()
"""


def _holder() -> subprocess.Popen[str]:
    child = subprocess.Popen(
        [sys.executable, "-c", _HOLDER],
        cwd=_REPO,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert child.stdout is not None
    assert child.stdout.readline().strip() == "HELD"
    return child


def test_lock_path_lives_under_the_isolated_claude_dir():
    assert "cortex_test_claude_" in str(consolidate_lock.LOCK_PATH)


def test_second_holder_in_the_same_process_is_refused():
    with consolidate_single_flight() as first:
        with consolidate_single_flight() as second:
            assert first is True
            assert second is False
    with consolidate_single_flight() as again:
        assert again is True


def test_handler_skips_while_another_process_consolidates():
    from mcp_server.handlers.consolidate import handler  # noqa: PLC0415 — heavy import, test scope

    child = _holder()
    try:
        result = asyncio.run(handler({"decay": True}))
    finally:
        child.communicate("\n", timeout=30)
    assert result == {"status": "skipped", "reason": "another consolidation is running"}


def test_kernel_releases_the_lock_of_a_killed_holder():
    child = _holder()
    child.kill()
    child.wait(timeout=30)
    with consolidate_single_flight() as held:
        assert held is True
