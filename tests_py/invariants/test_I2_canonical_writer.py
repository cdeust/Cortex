# noqa: N999 -- filename encodes the project's own invariant ID (I2, see
# docs/invariants/cortex-invariants.md and ADR-0053); renaming would break
# the formal invariant-ID cross-reference table and the ADR's own citation.
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
    - homeostatic_apply.py _apply_fold        (rare amortized fold UPDATE,
                                               per write class since M-D3)
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
    # Line pins re-computed on the 2026-07-11 merge train (7.2 + 7.4 +
    # silent-except-sweep + spread-activation) — each branch had pinned its own
    # pre-merge offsets; the test itself was used as the oracle.
    # All eleven pins shifted +1..+13 on the PLR2004/E501 sweep
    # (#197 family 3): named-constant extractions and line rewraps above
    # the writer sites moved them down; same writers, no new ones (the
    # test itself was the oracle, as on the 2026-07-11 re-pin).
    # Anchor transfer at supersession (read-path PR, decision 2026-07-07):
    # _transfer_anchor_on runs INSIDE the supersede transaction (bump_heat_raw
    # commits on its own connection, so routing through it would break
    # supersession atomicity). GREATEST(heat_base, old) never lowers heat.
    # Source: docs/program/pr2-read-path-supersession-audit.json.
    # Shifted 685->686 by the silent-except-sweep audit (2026-07-11) adding
    # one `from mcp_server.observability import silent_failure` import line
    # above this site.
    # Shifted 724->726 (and the two entries below by the same +2/+3) by the
    # S110 sweep (#197): teardown/DEALLOCATE excepts above these sites grew
    # a logger.debug line each.
    # Shifted 695->724 by the module-level hash helpers extraction
    # (feat/migrate-entrypoint, PR #101): compute_ddl_hash()/
    # read_schema_hash() were pulled out of PgMemoryStore as module-level
    # functions (net +29 lines above this site — 33 lines of new function
    # bodies/docstrings added, 4 lines of inline hash-computation removed
    # from _recorded_schema_hash, which now delegates to read_schema_hash).
    # Shifted -7 (pg_store) / -1 (anchor) by the PLC0415 sweep (#197
    # family 4): function-level imports above these sites hoisted to the
    # module top; same writers, no new ones (the test was the oracle,
    # as on every prior re-pin).
    # Shifted +5 (pg_store) / +2 (sqlite_store) by issue #252: both stores'
    # created_at normalization lost its `"T" not in raw_created` pre-test
    # (a substring test that skipped every string containing a T, e.g.
    # "8 May 2023 13:56 EST") and gained the comment explaining why; the
    # sqlite site also hoisted its function-level import. Same writers, no
    # new ones — this test was the oracle, as on every prior re-pin.
    #
    # pg_store.py (1384 lines, over the 300-line §4.1 cap) split into
    # concern-scoped Pg*Mixin modules (pg_store_heat.py, pg_store_supersede.py,
    # ...) behind the pg_store.py facade. Same three writers, relocated —
    # no new ones. _transfer_anchor_on's docstring (pg_store_supersede.py)
    # still explains why it cannot route through bump_heat_raw.
    ("infrastructure/pg_store_supersede.py", 169),
    # Canonical single-row writer (all callers route through this).
    ("infrastructure/pg_store_heat.py", 56),
    # A3 batched writer (homeostatic cohort branch + any other batch consumer).
    ("infrastructure/pg_store_heat.py", 154),
    # SQLite parity of the anchor transfer (same transactional rationale).
    # Shifted 389->440->447->493->529->530 (M-D3, then #169 added _fts_augment /
    # _migrate_fts_code_tokenize / unconditional embedding_model stamp above it;
    # then #206 added _register_json_codec above the class, +36 lines).
    # All three sqlite_store pins shifted +8 (549/579/643 -> 557/587/651) by
    # #368's capture-origin backfill: _run_column_migrations gained the
    # COLUMN_BACKFILLS import and turned its `except OperationalError: pass`
    # into `continue` + a conditional backfill execute (net +8 lines, all
    # above line 166). Same three writers, byte-identical SQL — verified by
    # diffing each site against origin/main; the test was the oracle, as on
    # every prior re-pin.
    ("infrastructure/sqlite_store.py", 557),
    # SQLite parity: canonical bump_heat_raw / update_memories_heat_batch.
    # Shifted 419->470->477->523->559->562, 463->534->541->587->623->626 for
    # the same
    # reasons (#169's _stamp_embedding_model / select_fallback_embeddings /
    # reembed_memory, then #206's _register_json_codec).
    ("infrastructure/sqlite_store.py", 587),
    ("infrastructure/sqlite_store.py", 651),
    # Homeostatic fold (amortized ~once/month per (domain, write_class)).
    # M-D3 (7.1, 2026-07-10): split out of homeostatic.py into
    # homeostatic_apply.py (§4.1 500-line file cap — stratification by
    # write class grew homeostatic.py past the limit). Same rare
    # amortized fold UPDATE, now scoped to a class's own source values.
    # Shifted 233->234 (issue #406): write_class import moved to
    # `from mcp_server.shared import write_class` (core/ -> shared/ move,
    # infrastructure/core layer-violation fix), adding one import line
    # above this site. Same writer, not new.
    ("handlers/consolidation/homeostatic_apply.py", 234),
    # Anchor pin: heat_base=1.0 + no_decay=TRUE preserves resist-decay.
    ("handlers/anchor.py", 149),
    # Preemptive boost: heat_base += 0.1 on Read/Edit/Write hook.
    # W2-4: private cooldown paths shifted these sites; both writer function
    # sources remain byte-identical to 3243dfed, including their A3 SQL.
    ("hooks/preemptive_context.py", 148),
    # Pipeline-impact boost: heat_base += 0.15 for symbols touched by an
    # edit, resolved via pipeline detect_changes (PostToolUse hook).
    ("hooks/pipeline_impact_bump.py", 184),
    # I6-D5 deliberate re-heat campaign (INC6.6): CAS-guarded single-row
    # writer. Cannot route through bump_heat_raw — that would (1) turn a
    # concurrent-write race into a silent overwrite instead of a detected
    # skip (apply_reheat's WHERE clause requires heat_base still equal to
    # the value observed at scan time) and (2) stamp heat_base_set_at,
    # resetting the decay clock the campaign's J+30 re-measurement
    # (2026-08-09) depends on staying untouched. Source: ADR-0053
    # (docs/adr/ADR-0053-deliberate-reheat-cas-writer-i2-exception.md).
    # Shifted 157->160 when M-D3 (7.1) added a write_class='auto' filter
    # comment to the homeostatic_state join above it.
    # Shifted 177->182 when the bare-container contract fix (5d71069c)
    # moved the module's psycopg import under TYPE_CHECKING, adding the
    # guard block above this writer.
    ("infrastructure/pg_store_memory_reheat.py", 183),
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
        # Relative to the scan root, never the absolute path. An agent
        # worktree lives at <repo>/.claude/worktrees/<name>/, so when the
        # suite runs FROM one, every absolute path contains "worktree" and
        # this check skipped the entire package: the scan found zero writers,
        # `unexpected` was empty, and the invariant passed vacuously — it
        # could not have caught a new unauthorized writer at all. Only the
        # stale-entry half of the assertion made the breakage visible.
        if "worktree" in str(py.relative_to(_MCP_ROOT)):
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
            if "UPDATE MEMORIES" in up and heat_base_assign.search(line):
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
def test_i2_no_unauthorized_heat_writes() -> None:
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
def test_i2_no_legacy_heat_column_writes() -> None:
    """Post-A3: no code should write the legacy ``heat`` column.

    The ``heat`` column was renamed to ``heat_base`` in the A3 migration.
    Any ``UPDATE memories SET heat = ...`` that is NOT followed by
    ``_base`` is a regression — the legacy writer has snuck back in.
    """
    offenders: set[tuple[str, int]] = set()
    for py in _MCP_ROOT.rglob("*.py"):
        # Relative to the scan root, never the absolute path. An agent
        # worktree lives at <repo>/.claude/worktrees/<name>/, so when the
        # suite runs FROM one, every absolute path contains "worktree" and
        # this check skipped the entire package: the scan found zero writers,
        # `unexpected` was empty, and the invariant passed vacuously — it
        # could not have caught a new unauthorized writer at all. Only the
        # stale-entry half of the assertion made the breakage visible.
        if "worktree" in str(py.relative_to(_MCP_ROOT)):
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
def test_i2_allow_list_not_empty() -> None:
    """Sanity: the allow-list must be populated — guards against scanner
    breaking silently."""
    assert len(_ALLOWED_WRITERS) > 0
