"""Layer: infrastructure. POSIX process-table command boundary.

Source: issue #682; CPython 3.12 Lib/subprocess.py (run byte streams and
CompletedProcess.returncode); ADR-1097 (probe failures must reach hook logging).
"""

from __future__ import annotations

import subprocess

# source: ADR-0597 — retain the existing process-probe deadline.
_PS_TIMEOUT_S = 1.0


class PsProbeError(OSError):
    """A failed process-table probe, with its command and stderr preserved."""

    def __init__(
        self,
        command: list[str],
        stderr: str,
        reason: str,
        returncode: int | None = None,
    ) -> None:
        self.command = command
        self.stderr = stderr
        self.returncode = returncode
        super().__init__(f"{command!r}: {reason}; stderr={stderr!r}")


def ps_output(columns: str, pid: int) -> str:
    """Return strict UTF-8 stdout; raise PsProbeError for an unusable probe.

    Read bytes so an invalid stdout cannot hide exit status or stderr.
    Diagnostic stderr uses backslashreplace to retain invalid bytes visibly;
    stdout stays strict because replacing process-name bytes changes identity.
    Source: issue #682; CPython 3.12 Lib/subprocess.py and bytes.decode contract.
    """
    command = ["ps", "-o", columns, "-p", str(pid)]
    try:
        out = subprocess.run(
            command,
            capture_output=True,
            timeout=_PS_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise PsProbeError(command, "", str(exc)) from exc
    stderr = out.stderr.decode("utf-8", errors="backslashreplace")
    if out.returncode != 0:
        raise PsProbeError(
            command, stderr, f"exit status {out.returncode}", out.returncode
        )
    try:
        return out.stdout.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise PsProbeError(command, stderr, str(exc), out.returncode) from exc
