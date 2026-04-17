"""Invariant I2 — canonical heat_base writer regression guard.

Formal predicate (from docs/invariants/cortex-invariants.md):
    The set of call-sites that issue ``UPDATE ... SET heat_base ...`` on
    ``memories`` is tightly bounded. Post-A3, no code writes the legacy
    ``heat`` column — all heat state is carried by ``heat_base``, and
    ``effective_heat()`` computes the decayed value at read time.

Allow-list (post-A3 single-canonical-path):
    - pg_store.py  bump_heat_raw              (canonical single-row writer)
    - pg_store.py  update_memories_heat_batch (A3 batched writer)
    - sqlite_store.py  bump_heat_raw          (SQLite parity single-row)
    - sqlite_store.py  update_memories_heat_batch (SQLite parity batch)
    - homeostatic.py _apply_fold              (rare amortized fold UPDATE)
    - anchor.py    anchor handler              (heat_base=1.0, no_decay=TRUE)
    - preemptive_context.py _prime_file_memories (heat_base boost on read/edit)

Any new writer outside this list fails this test.
"""

from __future__ import annotations

import pathlib

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_MCP_ROOT = _REPO_ROOT / "mcp_server"

# Post-A3 canonical writer allow-list. Each entry is a (relative_path,
# line_number) site that writes ``memories.heat_base``. Any new site must
# either route through ``bump_heat_raw`` / ``update_memories_heat_batch``
# OR be added here with a source-commented ADR justification.
_ALLOWED_WRITERS: set[tuple[str, int]] = {
    # Canonical single-row writer (all callers route through this).
    ("infrastructure/pg_store.py", 448),
    # A3 batched writer (homeostatic cohort branch + any other batch consumer).
    ("infrastructure/pg_store.py", 508),
    # SQLite parity.
    ("infrastructure/sqlite_store.py", 228),
    ("infrastructure/sqlite_store.py", 272),
    # Homeostatic fold (amortized ~once/month per domain).
    ("handlers/consolidation/homeostatic.py", 277),
    # Anchor pin: heat_base=1.0 + no_decay=TRUE preserves resist-decay.
    ("handlers/anchor.py", 140),
    # Preemptive boost: heat_base += 0.1 on Read/Edit/Write hook.
    ("hooks/preemptive_context.py", 136),
}


def _scan_heat_writers() -> set[tuple[str, int]]:
    """Static scan: every site that issues UPDATE memories SET heat_base.

    Tolerates multi-line SQL (looks at current line + preceding 5 lines
    to find the UPDATE MEMORIES clause associated with a SET HEAT_BASE line).
    Returns {(relative_path, line_number), ...} normalised to forward
    slashes for stable assertions across OSes.
    """
    import re

    # Match SET heat_base followed by whitespace/assignment/comma — NOT
    # heat_base_set_at (which is a timestamp we allow to be written freely).
    heat_base_assign = re.compile(r"SET\s+HEAT_BASE\s*(=|,|\+)", re.IGNORECASE)

    offenders: set[tuple[str, int]] = set()
    for py in _MCP_ROOT.rglob("*.py"):
        if "worktree" in str(py):
            continue
        try:
            src = py.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "heat_base" not in src.lower() or "UPDATE" not in src.upper():
            continue
        lines = src.splitlines()
        for i, line in enumerate(lines, 1):
            up = line.upper().replace(" AS M", "").replace(" AS W", "")
            # Single-line: UPDATE memories ... SET heat_base = ...
            if (
                "UPDATE MEMORIES" in up
                and heat_base_assign.search(line)
            ):
                rel = str(py.relative_to(_MCP_ROOT)).replace("\\", "/")
                offenders.add((rel, i))
                continue
            # Multi-line: a SET heat_base = line whose UPDATE memories clause
            # is in the preceding 5 lines.
            if heat_base_assign.search(line) and "MEMORIES" not in up:
                window = " ".join(lines[max(0, i - 6) : i]).upper()
                if "UPDATE MEMORIES" in window or '"MEMORIES"' in window:
                    rel = str(py.relative_to(_MCP_ROOT)).replace("\\", "/")
                    offenders.add((rel, i))
    return offenders


@pytest.mark.invariants
def test_I2_no_unauthorized_heat_writes() -> None:
    """I2: every UPDATE memories SET heat_base site must be in ALLOWED_WRITERS.

    Fails if a new writer is introduced (regression risk: silent drift
    from the canonical writer pattern). Fails also if a previously-listed
    writer has moved line number — update the allow-list with a source
    comment and consider whether the move reflects a refactor that should
    route through the canonical helper instead.
    """
    found = _scan_heat_writers()
    unexpected = found - _ALLOWED_WRITERS
    stale = _ALLOWED_WRITERS - found

    msg_parts: list[str] = []
    if unexpected:
        msg_parts.append(
            "New heat_base writer(s) introduced — each must either route "
            "through the canonical writer OR be added to ALLOWED_WRITERS "
            "with an ADR citation:\n  "
            + "\n  ".join(f"{p}:{ln}" for p, ln in sorted(unexpected))
        )
    if stale:
        msg_parts.append(
            "ALLOWED_WRITERS contains entries no longer present — "
            "update the list (line numbers may have shifted after refactor):\n  "
            + "\n  ".join(f"{p}:{ln}" for p, ln in sorted(stale))
        )

    assert not msg_parts, "\n\n".join(msg_parts)


@pytest.mark.invariants
def test_I2_no_legacy_heat_column_writes() -> None:
    """Post-A3: no code should write the legacy ``heat`` column.

    The ``heat`` column was renamed to ``heat_base`` in the A3 migration.
    Any ``UPDATE memories SET heat = ...`` that is NOT followed by
    ``_base`` is a regression — the legacy writer has snuck back in.
    """
    offenders: set[tuple[str, int]] = set()
    for py in _MCP_ROOT.rglob("*.py"):
        if "worktree" in str(py):
            continue
        try:
            src = py.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        lines = src.splitlines()
        for i, line in enumerate(lines, 1):
            up = line.upper()
            # Match "SET heat " (with trailing space/punct) but NOT "heat_base"
            if "UPDATE MEMORIES" in up and (
                "SET HEAT " in up
                or "SET HEAT=" in up
                or "SET HEAT =" in up
                or "SET HEAT," in up
            ):
                rel = str(py.relative_to(_MCP_ROOT)).replace("\\", "/")
                offenders.add((rel, i))

    assert not offenders, (
        "Legacy heat column writers found (should be heat_base post-A3):\n  "
        + "\n  ".join(f"{p}:{ln}" for p, ln in sorted(offenders))
    )


@pytest.mark.invariants
def test_I2_allow_list_not_empty() -> None:
    """Sanity: the allow-list must be populated — guards against scanner
    breaking silently."""
    assert len(_ALLOWED_WRITERS) > 0
