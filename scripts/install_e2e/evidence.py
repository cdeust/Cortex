"""Read what the host recorded: the SessionStart hook's fate, leftover processes.

Claude Code's ``--debug-file`` log is the only place the real host reports a
hook's exit status, duration and stdout; ``ps`` is the only proof that no
process the plugin started outlived the session.

source: scripts/install_e2e/host.py (the machine these read)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

# source: the owner's acceptance, brief step 0 -- strings a zero-ops user must never be told
FORBIDDEN = re.compile(r"brew|install .* manually|pip install|DATABASE_URL", re.IGNORECASE)
READY = "Cortex ready"  # source: the owner's acceptance, brief step 0
_FINISHED = re.compile(r"SessionStart:startup \[.*\] \(plugin hypermnesia-mcp@[^)]*\) finished with status (-?\d+) \((\d+)ms\)")
_TIMED_OUT = re.compile(r"SessionStart:startup \[.*\] \(plugin hypermnesia-mcp@[^)]*\) timed out after \d+ms \((\d+)ms\)")
_PAYLOAD = re.compile(r'"Hook SessionStart:startup \(SessionStart\) [a-z ]+:\\nstdout:\\n.*"')
SETTLE_POLL_SECONDS = 2  # source: ps cost is milliseconds; two seconds keeps the loop cheap


def session_start_outcome(debug_log: Path) -> dict:
    """The plugin's SessionStart hook as the host saw it: status, ms, stdout, stderr."""
    text = debug_log.read_text(errors="replace") if debug_log.exists() else ""
    lines = text.splitlines()
    for line in lines:
        timed_out = _TIMED_OUT.search(line)
        if timed_out:
            return {"status": None, "ms": int(timed_out.group(1)), "note": "host cancelled the hook at its timeout"}
    for index, line in enumerate(lines):
        finished = _FINISHED.search(line)
        if not finished:
            continue
        outcome = {"status": int(finished.group(1)), "ms": int(finished.group(2))}
        for later in lines[index + 1 : index + 4]:
            payload = _PAYLOAD.search(later)
            if payload:
                outcome.update(_split_payload(json.loads(payload.group(0))))
                break
        return outcome
    return {"status": None, "ms": None, "stdout": "", "stderr": "", "note": "hook never finished"}


def _split_payload(message: str) -> dict:
    _, _, rest = message.partition("stdout:\n")
    stdout, _, stderr = rest.partition("\nstderr:\n")
    return {"stdout": stdout, "stderr": stderr}


def system_message(stdout: str) -> str:
    """The ``systemMessage`` a JSON hook output shows the user, else ``""``."""
    stripped = stdout.strip()
    if not stripped.startswith("{"):
        return ""
    try:
        return str(json.loads(stripped).get("systemMessage", ""))
    except ValueError:
        return ""


def forbidden_lines(*texts: str) -> list:
    return [line for text in texts for line in text.splitlines() if FORBIDDEN.search(line)]


def _plugin_processes(markers: tuple) -> list:
    listing = subprocess.run(
        ["ps", "-axo", "pid=,command="], capture_output=True, text=True, check=True
    ).stdout
    own = {os.getpid(), os.getppid()}
    found = []
    for row in listing.splitlines():
        pid, _, command = row.strip().partition(" ")
        if pid.isdigit() and int(pid) not in own and any(m in command for m in markers):
            if "install_e2e" not in command:
                found.append(row.strip())
    return found


def wait_for_no_processes(markers: tuple, bound_seconds: float) -> dict:
    """Wait until no process names the machine; report what remained and how long."""
    started = time.monotonic()
    remaining = _plugin_processes(markers)
    while remaining and time.monotonic() - started < bound_seconds:
        time.sleep(SETTLE_POLL_SECONDS)
        remaining = _plugin_processes(markers)
    return {"seconds": round(time.monotonic() - started, 1), "remaining": remaining}
