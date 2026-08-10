"""Closed-world falsifiability guard for the write-class source taxonomy
(INC7.2 regression test).

This is the test that would have caught the INC7.1 bug (flagged, not
fixed, in that increment's own retro): ``pg_store_memory_reheat.py``
carried a hardcoded exact-match tuple ``("seed", "ingest", "cls")`` that
never matched the REAL DB source values (``"seed_project"``,
``"ingest_codebase"``, ``"cls-consolidation"`` — a prefix family, not an
exact string), so the "exclude auto/derived/mechanical" filter silently
excluded nothing beyond ``post_tool_capture``/``codebase_analyze``.

Two independent, falsifiable checks against the REAL dev DB corpus:

1. Any source string that *looks* auto-capture/derived/mechanical (shares
   the audit's own vocabulary — contains "seed", "ingest", "backfill",
   "codebase", "consolidation", "cls", or "post_tool_capture") must
   resolve to a NON-deliberate class. A source matching this vocabulary
   but classifying as DELIBERATE means the taxonomy's exact-match/prefix
   sets drifted from the real strings again.
2. Every DELIBERATE-classified real source must be in the reviewed
   allowlist below (exact set + reviewed prefixes). A new, never-reviewed
   source value silently landing in DELIBERATE via the safe default is
   not necessarily wrong -- but it must be a conscious decision, not an
   unnoticed default. This test forces that review by failing loudly.

Skipped without a live PostgreSQL dev DB (matches the rest of the
handler-level test suite's convention -- this is a corpus-shape guard,
not a pure-function unit test, so it needs the real ``memories`` table).
"""

from __future__ import annotations

import pytest

from mcp_server.shared.write_class import DELIBERATE, classify_write_class
from mcp_server.infrastructure.memory_config import get_memory_settings
from mcp_server.infrastructure.memory_store import get_shared_store

# Vocabulary shared with the I6/M-D2 audit's own "auto-capturées /
# backfill / mécaniques" description. Any real source containing one of
# these substrings must NOT classify as DELIBERATE.
_MECHANICAL_LOOKING_SUBSTRINGS = (
    "seed",
    "ingest",
    "backfill",
    "codebase",
    "consolidation",
    "cls",
    "post_tool_capture",
)

# Reviewed 2026-07-11 against the dev DB's 95 distinct `source` values
# (SELECT DISTINCT source FROM memories) -- every value that resolves to
# DELIBERATE under classify_write_class and was manually confirmed to be
# a genuine deliberate/user-authored write (feature, lesson, bug-fix,
# decision, benchmark record, wiki-indexed pointer, etc.), not an
# unreviewed accident of the safe default. Extend this set (with a
# comment noting the review date) when a new deliberate source family is
# introduced; do NOT extend it reflexively just to make this test pass.
_REVIEWED_DELIBERATE_EXACT_SOURCES: frozenset[str] = frozenset(
    {
        "analysis",
        "audit",
        "benchmark",
        "benchmark-audit",
        "bug-fix",
        "checkpoint",
        "collision-scan",
        "compliance-audit",
        "decision",
        "design",
        "design-analysis",
        "documentation-audit",
        "feature",
        "feature-removal",
        "investigation",
        "lesson",
        "literature-synthesis",
        "measurement",
        "observation",
        "parity-proof",
        "performance-lesson",
        "project",
        "reconnaissance",
        "refactor",
        "release-procedure",
        "research",
        "scan",
        "session",
        "setup",
        "user",
        "user-correction",
        "verification",
        "wiki-curation",
    }
)
_REVIEWED_DELIBERATE_PREFIXES: tuple[str, ...] = (
    "wiki://",  # wiki-indexed protected pointer entries
    "session-",  # session-<id> auto-labeled session summaries
    "memory-tool:",  # memory-tool:create/rethink/str_replace
)


def _pg_only():
    settings = get_memory_settings()
    store = get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)
    if not hasattr(store, "batch_pool"):
        pytest.skip("closed-world source taxonomy guard requires PostgreSQL")
    return store


def _distinct_sources(store) -> list[str]:
    with store.batch_pool.connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT DISTINCT source FROM memories")
        return [row[0] for row in cur.fetchall()]


class TestMechanicalVocabularyNeverDeliberate:
    def test_no_real_source_looks_mechanical_but_classifies_deliberate(self):
        store = _pg_only()
        offenders = []
        for source in _distinct_sources(store):
            looks_mechanical = any(
                substr in source.lower() for substr in _MECHANICAL_LOOKING_SUBSTRINGS
            )
            if looks_mechanical and classify_write_class(source) == DELIBERATE:
                offenders.append(source)
        assert offenders == [], (
            "source(s) share auto-capture/derived/mechanical vocabulary "
            f"but classify as DELIBERATE (taxonomy drift): {offenders!r}"
        )


class TestDeliberateSourcesAreReviewed:
    def test_every_deliberate_db_source_is_in_the_reviewed_allowlist(self):
        store = _pg_only()
        unreviewed = []
        for source in _distinct_sources(store):
            if classify_write_class(source) != DELIBERATE:
                continue
            if source in _REVIEWED_DELIBERATE_EXACT_SOURCES:
                continue
            if source.startswith(_REVIEWED_DELIBERATE_PREFIXES):
                continue
            unreviewed.append(source)
        assert unreviewed == [], (
            "new, unreviewed source(s) resolved to DELIBERATE via the "
            "safe default -- confirm this is intentional, then add to "
            f"_REVIEWED_DELIBERATE_EXACT_SOURCES/_PREFIXES: {unreviewed!r}"
        )
