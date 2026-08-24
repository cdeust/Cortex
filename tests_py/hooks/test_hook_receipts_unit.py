"""DB-free unit tests for the T2 hook receipt plumbing (decision 4255039).

Complements the PG-gated end-to-end tests in test_hook_receipts.py with
the branches those tests cannot reach deterministically:

* auto_recall's injection-budget drop — the parity invariant's teeth:
  a memory dropped by _MAX_INJECTION_CHARS was never in context and must
  not be attested by the receipt (correction 11). Killed mutants: moving
  ``included.append`` above the budget break, or returning the fetched
  list instead of the included one.
* the marker-less degradation rendering — a failed receipt write yields
  receipt_id=None and the banner must render WITHOUT a marker (I/O is
  the only named degradation mode; the injection itself never breaks).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from mcp_server.hooks.auto_recall import _MAX_INJECTION_CHARS, _format_injection
from mcp_server.hooks.session_start import _build_context


def _mem(mid: int, *, agent: str = "", content_len: int = 250) -> dict:
    return {
        "id": mid,
        "content": "y" * content_len,
        "heat": 0.9,
        "domain": "",
        "agent": agent,
        "protected": False,
    }


def test_budget_dropped_memory_is_excluded_from_included() -> None:
    # Each line renders as "- [<agent>] <200-char content>" ≈ 265 chars
    # with a 60-char agent prefix; the third line crosses the 800-char
    # budget and must be dropped from BOTH the text and the receipt list.
    memories = [
        _mem(1, agent="x" * 60),
        _mem(2, agent="x" * 60),
        _mem(3, agent="x" * 60),
    ]
    text, included = _format_injection(memories)

    assert len(text) <= _MAX_INJECTION_CHARS
    assert [m["id"] for m in included] == [1, 2]
    # Exactly the included entries are printed: header + one line each.
    assert len(text.splitlines()) == 1 + len(included)


def test_all_fitting_memories_are_included() -> None:
    memories = [_mem(1), _mem(2), _mem(3)]
    text, included = _format_injection(memories)
    assert [m["id"] for m in included] == [1, 2, 3]
    assert len(text.splitlines()) == 4


def test_nothing_fits_returns_empty_and_no_items() -> None:
    # A single line already over budget → no injection, no receipt items.
    text, included = _format_injection([_mem(1, agent="x" * 900)])
    assert text == ""
    assert included == []


def test_freshness_suffix_rendered_when_fields_present() -> None:
    # A memory carrying created_at / grade / stale gets an age·grade·stale
    # suffix (fleet-watch #110) — the harness-comparison "no age signal" fix.
    now = datetime(2026, 8, 24, 12, 0, 0, tzinfo=timezone.utc)
    mem = _mem(1, content_len=20)
    mem["created_at"] = now - timedelta(days=90)
    mem["source_attribution"] = "verified"
    mem["is_stale"] = True
    text, included = _format_injection([mem], now=now)
    assert "3mo ago" in text
    assert "src=verified" in text
    assert "⚠stale" in text
    assert [m["id"] for m in included] == [1]


def test_bare_memory_has_no_suffix() -> None:
    # Memories without freshness fields render exactly as before (no suffix),
    # so existing call sites and budgets are unaffected.
    now = datetime(2026, 8, 24, 12, 0, 0, tzinfo=timezone.utc)
    text, _ = _format_injection([_mem(1, content_len=20)], now=now)
    assert " · " not in text


def test_banner_renders_marker_only_with_receipt() -> None:
    anchors = [{"id": 1, "content": "a fact", "domain": "", "is_global": False}]

    with_receipt = _build_context(anchors, [], None, receipt_id=57)
    assert "⟦rcpt:57⟧" in with_receipt.splitlines()[0]

    # Failed receipt write (None) → marker-less banner, injection intact.
    without = _build_context(anchors, [], None, receipt_id=None)
    assert "⟦rcpt:" not in without
    assert "a fact" in without


def test_stale_grooming_renders_one_line_not_a_section() -> None:
    """G-4: the staleness reminder is ONE line, never a header + block --
    the 76-day-silent-wiki lesson is that a full section (like the
    existing "Pending Wiki Curation" one) becomes just another ignored
    nudge once it's permanently present."""
    anchors = [{"id": 1, "content": "a fact", "domain": "", "is_global": False}]

    ctx = _build_context(
        anchors, [], None, stale_grooming=["distillation", "promotion"]
    )
    lines = ctx.splitlines()
    reminder_lines = [
        line
        for line in lines
        if "Grooming overdue" in line or "get_grooming_health" in line
    ]
    assert len(reminder_lines) == 1
    assert "distillation/promotion" in reminder_lines[0]
    # No new markdown header was introduced for this reminder.
    assert not any(line.startswith("###") and "Grooming" in line for line in lines)


def test_no_stale_grooming_omits_reminder() -> None:
    anchors = [{"id": 1, "content": "a fact", "domain": "", "is_global": False}]
    ctx = _build_context(anchors, [], None, stale_grooming=[])
    assert "Grooming overdue" not in ctx
    assert "get_grooming_health" not in ctx


def test_stale_grooming_alone_triggers_context_build() -> None:
    """Even with no anchors/hot/checkpoint/pending_curations, a stale
    grooming signal alone must not degrade to an empty banner (the
    guard clause explicitly checks it)."""
    ctx = _build_context([], [], None, stale_grooming=["wiki"])
    assert ctx != ""
    assert "Grooming overdue (wiki)" in ctx
