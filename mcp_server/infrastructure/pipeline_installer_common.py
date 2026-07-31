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
        proc = subprocess.run(  # noqa: S603 — every caller passes a fixed-shape argv (git/cargo/sh with resolved-binary or verified-path args, never shell=True); the one `sh -c <str>` caller (pipeline_install_rust.py's curl|sh fallback) builds that string from a hardcoded https:// literal + shutil.which("curl"), both shlex.quote()'d
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
    except Exception as exc:  # noqa: BLE001 — subprocess wrapper contract — any spawn failure is returned as (-2, message)
        return -2, str(exc)


def _rmtree_quiet(path: Path) -> None:
    """``shutil.rmtree`` with no error escalation (best-effort cleanup)."""
    try:
        shutil.rmtree(path, ignore_errors=True)
    except OSError:
        # ignore_errors=True already swallows per-entry failures; this
        # guards path-level errors (e.g. unstatable mount) the flag misses.
        pass
