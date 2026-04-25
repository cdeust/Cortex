"""Shared subprocess helper for the pipeline installer modules.

Kept in its own module so pipeline_install_rust and pipeline_installer
don't need to cross-import for a 20-line utility (which would also be
awkward — pipeline_installer already imports from
pipeline_install_rust).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Optional


def _run_quiet(
    cmd: list[str],
    cwd: Optional[str] = None,
    timeout: int = 600,
    env: Optional[dict] = None,
) -> tuple[int, str]:
    """Run ``cmd`` capturing stderr only. Returns (returncode, stderr_tail).

    Stdout is discarded. Stderr's last 4 KiB is returned for diagnostics
    (kept short — failures are logged, not displayed). Pass ``env`` to
    override the inherited environment.
    """
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        tail = (proc.stderr or b"").decode("utf-8", errors="replace")[-4096:]
        return proc.returncode, tail
    except subprocess.TimeoutExpired:
        return -1, f"timeout after {timeout}s"
    except Exception as exc:
        return -2, str(exc)


def _rmtree_quiet(path: Path) -> None:
    """``shutil.rmtree`` with no error escalation (best-effort cleanup)."""
    try:
        shutil.rmtree(path, ignore_errors=True)
    except Exception:
        pass
