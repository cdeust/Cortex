"""Per-cell checkpoint/resume state for the trust-factor sweep (issue #368).

2026-08-10 incident: five sweep campaigns died over one session, each with a
different attributed cause (CPU contention, a native crash, a missing
dataset file, a session gap, a noisy neighbor). Five explanations for five
occurrences of the same symptom was itself the signal missed at the time:
those four "causes" described the state found on wake-up, not the actual
failure mechanism. The mechanism is that a long-running job driven from a
sub-agent's own foreground loop does not survive whatever ends that
sub-agent's turn -- confirmed by a neighboring session that measured the
identical failure shape on five unrelated tasks, and that succeeded only
once it stopped depending on that survival.

The fix is not to prevent the death (it cannot be prevented from here) but
to make it cost one cell, not the whole grid: `trust_factor_sweep.sh` now
runs exactly ONE pending cell per invocation and returns control immediately
after, recording that cell's completion (grid point, result location, code
sha, and machine-load/disk-space snapshots at both cell start and cell end)
to a fixed-location PROGRESS.json. A killed or crashed run leaves no entry
for the cell it was running, so the next invocation finds it still pending
and retries exactly that one -- never the cells already recorded.

The load/disk snapshots are NOT a defence against this failure mode (a kill
happens regardless of what they read) -- they remain what they were built
for: metadata that lets a later reader requalify a cell's number without
trusting the runner's word for it. Load and disk are deliberately two
separate signals, not redundant: load average integrates I/O wait as well
as CPU, so it rises under a saturated disk with no CPU contention at all.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

PROGRESS_FILENAME = "PROGRESS.json"


def _git_sha() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return out.stdout.strip() if out.returncode == 0 else "unknown"


def read_progress(sweep_dir: str) -> dict:
    """Read PROGRESS.json, or an empty structure if absent/unreadable --
    never raises, matching this project's other best-effort snapshot code."""
    path = Path(sweep_dir) / PROGRESS_FILENAME
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {"cells": []}


def completed_w_values(sweep_dir: str) -> set[float]:
    progress = read_progress(sweep_dir)
    return {c["w"] for c in progress.get("cells", []) if c.get("status") == "complete"}


def next_pending_w(grid: list[float], sweep_dir: str) -> float | None:
    """First grid value with no `status: complete` entry, in grid order, or
    None once every cell has one -- the resume point after a kill/crash."""
    done = completed_w_values(sweep_dir)
    for w in grid:
        if w not in done:
            return w
    return None


def record_cell_result(
    sweep_dir: str,
    w: float,
    *,
    status: str,
    repro_dir: str | None,
    snapshots: dict,
) -> None:
    """Append (or replace) one cell's completion record in PROGRESS.json.

    `snapshots` carries the four points this incident asks for:
    machine_load_at_start/_at_end, disk_space_at_start/_at_end -- passed as
    one dict rather than four parameters to stay under this project's
    4-argument-max convention (coding-standards.md §3.2) without losing any
    of the four points to a size-cap-driven abbreviation.
    """
    progress = read_progress(sweep_dir)
    progress.setdefault("cells", [])
    progress["cells"] = [c for c in progress["cells"] if c.get("w") != w]
    progress["cells"].append(
        {
            "w": w,
            "status": status,
            "git_sha": _git_sha(),
            "repro_dir": repro_dir,
            **snapshots,
        }
    )
    path = Path(sweep_dir) / PROGRESS_FILENAME
    path.write_text(json.dumps(progress, indent=2))
