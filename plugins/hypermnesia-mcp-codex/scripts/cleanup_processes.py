"""Fail-closed process checks ported from disk-hygiene."""

# Source: ADR-1092 — lsof ownership guard.
import os
import subprocess
from cleanup_registry import Protected


def no_open_files(path):
    """lsof exits 1 for no matches; errors also exit 1 but carry stderr."""
    try:
        scope = ["+D", path] if os.path.isdir(path) else [path]
        result = subprocess.run(
            ["lsof", "-Fftn", *scope], text=True, capture_output=True, timeout=30
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise Protected(f"cannot verify active processes: {exc}") from exc
    if result.stderr.strip() or result.returncode not in (0, 1):
        raise Protected(
            "lsof could not verify active processes: " + result.stderr.strip()
        )
    descriptor, kind = "", ""
    for line in result.stdout.splitlines():
        if line.startswith("f"):
            descriptor, kind = line[1:], ""
        elif line.startswith("t"):
            kind = line[1:]
        elif line.startswith("n") and (descriptor in ("cwd", "txt") or kind != "DIR"):
            raise Protected("active process uses " + line[1:])
