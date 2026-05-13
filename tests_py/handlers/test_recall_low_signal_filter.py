"""Tests for the low-signal filter on the recall path.

Spike 2026-05-13 found that recall results for design-decision queries
were dominated by ``# Tool: Edit`` auto-captures from unrelated repos.
The filter drops memories tagged ``auto-captured`` / ``tool:edit`` /
``_backfill`` / ``stage-N`` etc. unless the caller opts in.
"""

from __future__ import annotations

from mcp_server.handlers.recall_helpers import (
    LOW_SIGNAL_TAGS,
    filter_low_signal,
)


def _mem(content: str, *tags: str) -> dict:
    """Build a minimal result dict that matches recall's output shape."""
    return {
        "memory_id": id(content),
        "content": content,
        "score": 0.9,
        "tags": list(tags),
    }


# ── Filter behaviour ──────────────────────────────────────────────────


def test_tool_edit_capture_is_dropped() -> None:
    results = [_mem("# Tool: Edit\nfile.py changed", "auto-captured", "tool:edit")]
    kept, dropped = filter_low_signal(results)
    assert kept == []
    assert dropped == 1


def test_backfill_import_is_dropped() -> None:
    results = [_mem("Some bulk-imported note", "imported", "_backfill")]
    kept, dropped = filter_low_signal(results)
    assert kept == []
    assert dropped == 1


def test_stage_report_is_dropped() -> None:
    results = [_mem("stage 3 research verdict", "stage-3", "research")]
    kept, dropped = filter_low_signal(results)
    assert kept == []
    assert dropped == 1


def test_curated_lesson_is_kept() -> None:
    """A lesson memory tagged with knowledge-shaped tags must survive."""
    results = [_mem("The bug was X; the fix was Y.", "lesson", "bug-fix")]
    kept, dropped = filter_low_signal(results)
    assert len(kept) == 1
    assert dropped == 0


def test_decision_record_is_kept() -> None:
    results = [_mem("Decision: adopt pgvector for ANN.", "decision", "architecture")]
    kept, dropped = filter_low_signal(results)
    assert len(kept) == 1
    assert dropped == 0


def test_convention_memory_is_kept() -> None:
    results = [_mem("Always use slugify before .md append.", "convention", "rule")]
    kept, dropped = filter_low_signal(results)
    assert len(kept) == 1
    assert dropped == 0


# ── Mixed-batch realism: spike scenario ───────────────────────────────


def test_filter_clears_tool_noise_so_lesson_floats_up() -> None:
    """Models the exact spike result: 4 tool-output captures + 1 lesson.
    Filtering must surface the lesson as the only kept hit."""
    results = [
        _mem("# Tool: Edit\nfile1.py changed", "auto-captured", "tool:edit"),
        _mem("# Tool: Edit\nfile2.py changed", "auto-captured", "tool:edit"),
        _mem("# Tool: Bash\ngit status", "auto-captured", "tool:bash"),
        _mem(
            "Decision: 001-zero-dependencies — use Node built-ins only.",
            "decision",
            "adr",
        ),
        _mem("# Tool: Read\nopened file", "auto-captured", "tool:read"),
    ]
    kept, dropped = filter_low_signal(results)
    assert len(kept) == 1
    assert dropped == 4
    assert "Decision: 001-zero-dependencies" in kept[0]["content"]


# ── String-encoded tags (PG returns tags as JSON-encoded string) ──────


def test_tags_as_json_string_still_filtered() -> None:
    """PG store can serialize tags as a JSON string; the filter must
    parse and apply correctly either way."""
    results = [
        {
            "memory_id": 1,
            "content": "tool capture",
            "tags": '["auto-captured", "tool:edit"]',
        }
    ]
    kept, dropped = filter_low_signal(results)
    assert kept == []
    assert dropped == 1


def test_empty_tags_kept() -> None:
    """A memory with no tags at all is not low-signal."""
    results = [{"memory_id": 1, "content": "untagged memory", "tags": []}]
    kept, dropped = filter_low_signal(results)
    assert len(kept) == 1
    assert dropped == 0


def test_missing_tags_key_kept() -> None:
    """Defensive: a result dict that's missing the ``tags`` key is kept."""
    results = [{"memory_id": 1, "content": "untagged memory"}]
    kept, dropped = filter_low_signal(results)
    assert len(kept) == 1


# ── Set membership invariants ─────────────────────────────────────────


def test_low_signal_tags_covers_known_polluters() -> None:
    """Pin the canonical set so a refactor can't silently shrink it."""
    must_include = {
        "auto-captured",
        "tool:edit",
        "tool:bash",
        "_backfill",
        "imported",
        "session-summary",
        "stage-1",
        "stage-11",
    }
    assert must_include.issubset(LOW_SIGNAL_TAGS)


def test_low_signal_tags_does_not_include_knowledge_signals() -> None:
    """Pin the negative: knowledge-shaped tags must NOT be in the filter."""
    must_exclude = {
        "decision",
        "adr",
        "lesson",
        "convention",
        "architecture",
        "design",
        "rule",
        "standard",
    }
    assert not (must_exclude & LOW_SIGNAL_TAGS)
