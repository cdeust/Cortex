"""Kill-without-recollect subprocess execution — the shared #94 fix.

Windows subprocess pipe-handle deadlock (cdeust/Cortex#91, #94):
``subprocess.run``/``check_output``'s own ``TimeoutExpired`` handling
calls ``Popen.communicate()`` a *second* time, with no deadline, after
killing the child (CPython ``subprocess.py``, ``Popen.__exit__`` /
``run()``'s except-block, as of 3.13 — see cdeust/Cortex#91 for the full
mechanism and a live Windows reproduction). That second call can block
forever if a concurrently-spawned sibling process (e.g. the
automatised-pipeline upstream bridge, ``CORTEX_MEMORY_AP_ENABLED=1`` by
default) inherited the pipe's write handle — the trap fires *inside*
``subprocess.run`` itself, before any ``except TimeoutExpired:`` in the
caller ever runs.

``run_with_hard_timeout`` open-codes ``Popen`` + one bounded
``communicate()`` and, on timeout, kills the process and returns the
degraded result (``None``) without ever calling ``communicate()`` again —
breaking the trap at its source rather than catching the hang after the
fact. Its call sites are ``handlers/auto_task_record_writer.py`` and
``handlers/validate_memory.py`` (see cdeust/Cortex#94); a third,
``infrastructure/git_diff_exec.py``, was removed with the unwired
git-diff module in #196.

Pure stdlib — no I/O policy beyond running the given argv. Shared layer:
depends on the standard library only.
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

    On timeout: kills the child and reaps its exit status via a
    short-bounded ``wait()`` — safe because ``wait()`` alone never reads
    the pipes (only ``communicate()`` does), so it cannot re-trigger the
    handle-inheritance deadlock this function exists to avoid. If even
    that bounded reap times out, the zombie is abandoned rather than
    risking a second unbounded block — acceptable because this process
    is long-lived and the OS reclaims the slot when the parent exits.
    """
    try:
        proc = subprocess.Popen(  # noqa: S603 — documented contract above: "Caller owns argument sanitization — this function does not interpret cmd"; shell=False always, per the same precondition
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
