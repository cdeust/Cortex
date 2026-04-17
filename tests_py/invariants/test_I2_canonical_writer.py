"""Invariant I2 — canonical heat writer regression guard.

Formal predicate (from docs/invariants/cortex-invariants.md):
    |{call-sites that issue UPDATE ... SET heat ... ON memories}| = 1 post-A3
    Pre-A3: the allow-list below is the frozen set of known writers; any
    new writer outside the list fails this test.

Why this test exists:
    The emergence_tracker AttributeError bug (darval issue #13, fixed in
    c5a1862) was a "split module, caller not updated" regression: when
    emergence_tracker.py was split to satisfy the 300-line cap,
    generate_emergence_report moved to emergence_metrics.py but the
    caller in consolidate.py wasn't updated. The same class of risk
    applies to any code that writes raw heat directly — if A3 introduces
    a new canonical helper (store.bump_heat_raw) but a new site writes
    UPDATE memories SET heat = X outside that helper, the invariant
    silently drifts. This test catches that drift at CI time.

Post-A3 evolution:
    The ALLOWED_WRITERS set shrinks to exactly 1 (the canonical helper)
    when the A3 migration (docs/program/) lands. The test is intentionally
    strict: any addition requires explicit ADR justification and an update
    to the allow-list with a source comment.
"""

from __future__ import annotations

import pathlib

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_MCP_ROOT = _REPO_ROOT / "mcp_server"

# Pre-A3 allow-list (frozen 2026-04-16 after Curie I4 audit).
# Each entry is a (relative_path, line_number) site that directly writes
# memories.heat. Post-A3, this list collapses to exactly one canonical
# helper (store.bump_heat_raw). Any new site must either:
#   (a) route through the canonical helper, OR
#   (b) be added here with a source-commented ADR justification.
_ALLOWED_WRITERS: set[tuple[str, int]] = {
    # Pre-A3 per-row writer (dispatches to bump_heat_raw when flag=true).
    ("infrastructure/pg_store.py", 257),
    # A3 canonical heat_base writer (bump_heat_raw) — the ONE post-A3
    # site once step 10 collapses the allow-list.
    ("infrastructure/pg_store.py", 277),
    # Pre-A3 batch UNNEST writer — deleted in a3-step-8 (homeostatic rewrite).
    ("infrastructure/pg_store.py", 336),
    # Anchor handler, A3-branch (heat_base + no_decay post-migration).
    ("handlers/anchor.py", 145),
    # Anchor handler, legacy branch (heat column pre-migration).
    ("handlers/anchor.py", 152),
    # Preemptive context, A3-branch (heat_base + heat_base_set_at).
    ("hooks/preemptive_context.py", 143),
    # Preemptive context, legacy branch (heat column).
    ("hooks/preemptive_context.py", 156),
    # Decay SQL inside DECAY_MEMORIES_FN. Deleted in a3-step-7.
    ("infrastructure/pg_schema.py", 739),
    # Codebase-analyze stale marker, legacy branch only (A3 drops
    # the heat=0 clause as redundant with is_stale=TRUE).
    ("handlers/codebase_analyze_helpers.py", 162),
    # SQLite fallback backend mirrors the Postgres writers.
    # Line numbers shifted (214→224, 230→235) when bump_heat_raw +
    # get/set_homeostatic_factor were added for A3 parity.
    ("infrastructure/sqlite_store.py", 224),  # update_memory_heat legacy
    ("infrastructure/sqlite_store.py", 235),  # bump_heat_raw (A3 canonical)
    ("infrastructure/sqlite_store.py", 279),  # update_memories_heat_batch legacy
}


def _scan_heat_writers() -> set[tuple[str, int]]:
    """Static scan: every site that issues UPDATE memories SET heat.

    Tolerates multi-line SQL (looks at current line + preceding 5 lines
    to find the UPDATE MEMORIES clause associated with a SET HEAT line).
    Returns {(relative_path, line_number), ...} normalised to forward
    slashes for stable assertions across OSes.
    """
    offenders: set[tuple[str, int]] = set()
    for py in _MCP_ROOT.rglob("*.py"):
        if "worktree" in str(py):
            continue
        try:
            src = py.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "heat" not in src.lower() or "UPDATE" not in src.upper():
            continue
        lines = src.splitlines()
        for i, line in enumerate(lines, 1):
            up = line.upper().replace(" AS M", "").replace(" AS W", "")
            # Single-line: UPDATE memories SET ... heat ...
            if (
                "UPDATE MEMORIES" in up
                and "SET" in up
                and ("HEAT" in up or "HEAT_BASE" in up)
            ):
                rel = str(py.relative_to(_MCP_ROOT)).replace("\\", "/")
                offenders.add((rel, i))
                continue
            # Multi-line: a SET heat line whose UPDATE memories clause
            # is in the preceding 5 lines.
            if "SET HEAT" in up and "MEMORIES" not in up:
                window = " ".join(lines[max(0, i - 6) : i]).upper()
                if "UPDATE MEMORIES" in window or '"MEMORIES"' in window:
                    rel = str(py.relative_to(_MCP_ROOT)).replace("\\", "/")
                    offenders.add((rel, i))
    return offenders


@pytest.mark.invariants
def test_I2_no_unauthorized_heat_writes() -> None:
    """I2: every UPDATE memories SET heat site must be in ALLOWED_WRITERS.

    Fails if a new writer is introduced (regression risk: silent drift
    from the canonical writer pattern A3 will enforce). Fails also if a
    previously-listed writer has moved line number — update the
    allow-list with a source comment and consider whether the move
    reflects a refactor that should route through the canonical helper
    instead.
    """
    found = _scan_heat_writers()
    unexpected = found - _ALLOWED_WRITERS
    stale = _ALLOWED_WRITERS - found

    msg_parts: list[str] = []
    if unexpected:
        msg_parts.append(
            "New heat writer(s) introduced — each must either route "
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
def test_I2_allow_list_not_empty() -> None:
    """Sanity: the allow-list must be populated. A zero-length list would
    make test_I2_no_unauthorized_heat_writes pass vacuously whenever
    every writer site has been removed (good) OR whenever the scanner
    breaks silently (bad). Explicit non-empty assertion keeps the test
    honest across refactors.
    """
    assert len(_ALLOWED_WRITERS) > 0, (
        "ALLOWED_WRITERS is empty. If A3 has landed and collapsed all "
        "writers to the canonical helper, this test should be updated "
        "to assert exactly that one site — not left empty."
    )
