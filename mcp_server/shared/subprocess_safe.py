"""Execute subprocesses with timeout termination and bounded cleanup.

source: ADR-0667
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def run_with_hard_timeout(
    cmd: list[str],
    *,
    cwd: str | Path | None = None,
    timeout: float,
    encoding: str | None = None,
) -> str | None:
    """Run ``cmd``, returning stdout on success or ``None`` on any failure.

    precondition: ``cmd`` is a non-empty argv list (``shell=False``
    semantics always). Caller owns argument sanitization — this function
    does not interpret ``cmd``. ``timeout`` is in seconds, > 0.
    postcondition: returns stripped stdout (``str``, possibly ``""`` for
    a successful command with no output) when the process exits with
    code 0 within ``timeout``. Returns ``None`` when: the binary cannot
    be spawned (``FileNotFoundError``/``OSError``), the process exceeds
    ``timeout`` (killed, not waited-on-forever), or it exits non-zero.
    Never raises — every failure mode degrades to ``None``, and callers
    are expected to treat ``None`` the same as ``""``/empty-result.

    source: ADR-0667"""
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd) if cwd is not None else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding=encoding,
        )
    except (FileNotFoundError, OSError):
        return None

    try:
        stdout, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        return None
    except (OSError, ValueError):
        proc.kill()
        return None

    if proc.returncode != 0:
        return None
    return stdout.strip() if stdout else ""


__all__ = ["run_with_hard_timeout"]
