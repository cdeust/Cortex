"""Read what the host recorded: the SessionStart hook's fate, leftover processes.

Claude Code's ``--debug-file`` log is the only place the real host reports a
hook's exit status, duration and stdout; process records (POSIX ``ps`` or
Windows CIM) check whether a process naming this disposable install outlived
the session.

source: scripts/install_e2e/host.py (the machine these read)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

# Strings a zero-ops user must never be told.
# source: the owner's acceptance, brief step 0
FORBIDDEN = re.compile(
    r"brew|install .* manually|pip install|DATABASE_URL", re.IGNORECASE
)
READY = "Cortex ready"  # source: the owner's acceptance, brief step 0
_HOOK = r"SessionStart:startup \[.*\] \(plugin hypermnesia-mcp@[^)]*\) "
_FINISHED = re.compile(_HOOK + r"finished with status (-?\d+) \((\d+)ms\)")
_TIMED_OUT = re.compile(_HOOK + r"timed out after \d+ms \((\d+)ms\)")
# A finished hook's output line: ``success:`` carries stdout, a non-zero exit
# ``error: status code N`` carries only stderr (claude 2.1.296/2.1.300 debug log).
_PAYLOAD = re.compile(
    r'"Hook SessionStart:startup \(SessionStart\) '
    r"[a-z ]+:(?: status code \d+)?\\n(?:stdout|stderr):\\n.*\""
)
SETTLE_POLL_SECONDS = (
    2  # source: ps cost is milliseconds; two seconds keeps the loop cheap
)


def session_start_outcome(debug_log: Path) -> dict:
    """The plugin's SessionStart hook as the host saw it: status, ms, stdout, stderr."""
    text = debug_log.read_text(errors="replace") if debug_log.exists() else ""
    lines = text.splitlines()
    for line in lines:
        timed_out = _TIMED_OUT.search(line)
        if timed_out:
            return {
                "status": None,
                "ms": int(timed_out.group(1)),
                "note": "host cancelled the hook at its timeout",
            }
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
    return {
        "status": None,
        "ms": None,
        "stdout": "",
        "stderr": "",
        "note": "hook never finished",
    }


def _split_payload(message: str) -> dict:
    if "stdout:\n" not in message:  # a non-zero exit: stderr only
        return {"stdout": "", "stderr": message.partition("stderr:\n")[2]}
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
    return [
        line for text in texts for line in text.splitlines() if FORBIDDEN.search(line)
    ]


def _diagnostic_text(text: str) -> str:
    """Keep installer errors, removing authorization lines and URL access data."""

    def clean_url(match: re.Match) -> str:
        try:
            parts = urlsplit(match.group())
        except ValueError:
            return "[redacted malformed URL]"
        return urlunsplit(
            (parts.scheme, parts.netloc.rsplit("@", 1)[-1], parts.path, "", "")
        )

    lines = []
    for line in text.splitlines(keepends=True):
        if re.search(
            r"(?i)(password|passwd|token|secret|authorization|api[_-]?key)\b", line
        ):
            lines.append("[redacted sensitive diagnostic line]\n")
        else:
            lines.append(
                re.sub(r"(?:https?|postgresql)://[^\s\"'<>]+", clean_url, line)
            )
    return "".join(lines)


def setup_failure_logs(data: Path, work: Path) -> dict[str, str]:
    """Read only the owned install's known logs, before later sessions modify them."""
    root = data.resolve()
    if not root.is_relative_to(work.resolve()):
        return {"error": "refused plugin data outside owned work"}
    found = {}
    # source: log filenames defined by launcher_setup.py and launcher_base_job.py.
    for name in ("setup.log", "deps-install.log"):
        path = data / name
        if path.is_symlink() or path.resolve().parent != root:
            found[name] = "refused log outside owned plugin data"
        elif path.is_file():
            try:
                found[name] = _diagnostic_text(
                    path.read_text(encoding="utf-8", errors="replace")
                )
            except OSError as exc:
                found[name] = f"log unreadable: {type(exc).__name__}"
    return found or {"error": "no Setup or dependency log was written"}


def _windows_processes(markers: tuple) -> list:
    # WMI exposes native Windows processes; Git Bash ps sees only MSYS processes.
    # https://learn.microsoft.com/en-us/windows/win32/cimwin32prov/win32-process
    command = r"""$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$markers = ConvertFrom-Json $env:CORTEX_INSTALL_PROCESS_MARKERS
$rows = @(Get-CimInstance Win32_Process | Where-Object {
  $line = if ($_.CommandLine) { $_.CommandLine.Replace('\', '/').ToLowerInvariant() }
  $line -and @($markers | Where-Object { $line.Contains($_) }).Count -gt 0
} | Select-Object ProcessId, CommandLine)
ConvertTo-Json -InputObject $rows -Compress
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        env={
            **os.environ,
            "CORTEX_INSTALL_PROCESS_MARKERS": json.dumps(
                [m.replace("\\", "/").casefold() for m in markers]
            ),
        },
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    rows = json.loads(result.stdout.lstrip("\ufeff"))
    return [(int(row["ProcessId"]), row["CommandLine"]) for row in rows]


def _plugin_processes(markers: tuple) -> list:
    if os.name == "nt":
        rows = _windows_processes(markers)
    else:
        listing = subprocess.run(
            ["ps", "-axo", "pid=,command="], capture_output=True, text=True, check=True
        ).stdout
        rows = []
        for line in listing.splitlines():
            pid, _, command = line.strip().partition(" ")
            if pid.isdigit():
                rows.append((int(pid), command))
    own = {os.getpid(), os.getppid()}
    if os.name == "nt":
        markers = tuple(marker.replace("\\", "/").casefold() for marker in markers)
    return [
        f"{pid} {command}"
        for pid, command in rows
        if pid not in own
        and "install_e2e" not in command
        and any(
            marker
            in (command.replace("\\", "/").casefold() if os.name == "nt" else command)
            for marker in markers
        )
    ]


def wait_for_no_processes(markers: tuple, bound_seconds: float) -> dict:
    """Wait until no process names the machine; report what remained and how long."""
    started = time.monotonic()
    remaining = _plugin_processes(markers)
    while remaining and time.monotonic() - started < bound_seconds:
        time.sleep(SETTLE_POLL_SECONDS)
        remaining = _plugin_processes(markers)
    return {"seconds": round(time.monotonic() - started, 1), "remaining": remaining}
