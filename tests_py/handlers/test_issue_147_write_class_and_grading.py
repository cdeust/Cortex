"""Regression tests for issue #147.

Two independent write-path defects observed in one MCP session, initially
suspected to share a root cause but resolved to two distinct ones (Move 4,
engineer.md — "classify the cause"):

1. ``write_class="deliberate"`` (or omitted, source-fallback to deliberate)
   was rejected by the novelty gate — violating the tool's documented
   contract ("deliberate — NEVER rejected by the gate for low novelty").
   Root cause: ``handlers/remember.py`` computed ``resolved_write_class``
   but never threaded it into ``evaluate_gate`` -> ``determine_bypass``,
   which had zero knowledge of write_class. Fixed by threading
   ``write_class`` through ``evaluate_gate`` / ``_compute_gate_decision``
   / ``core.write_gate.determine_bypass``.

2. ``force=True`` (and plain, non-forced writes) intermittently raised a
   bare ``FileNotFoundError`` with a misleading "check DATABASE_URL" hint,
   even with a healthy PG connection. Root cause: the write-time provenance
   grading step (``handlers/remember_helpers.py::insert_and_post_process``
   calling ``validate_memory.grade_from_content(..., base_dir=directory or
   os.getcwd())``) was the ONE unguarded I/O-adjacent call in a function
   whose every other enrichment step (source_attribution, habituation
   signature) is already wrapped defensively. ``os.getcwd()`` raises
   ``FileNotFoundError`` when the process cwd has been removed (e.g. a
   worktree cleanup mid-session) — unrelated to the DB. Fixed by wrapping
   the grading call in ``_grade_content_best_effort`` (never raises;
   returns a diagnostic UNVERIFIABLE report + an observable
   ``prov-grading-failed:<ExceptionType>`` tag on failure) and by removing
   the misleading DATABASE_URL hint for exception types
   ``tool_error_handler._classify_error`` did not recognize as DB-related.

The third symptom in the issue (``reason: "bypass_error"`` on a
SUCCESSFUL store) was investigated and found to be BY DESIGN, not a bug:
``bypass_error`` is the ``gate_reason`` for content that matches the
error/exception-keyword regex (``core.thermodynamics.is_error_content``)
— see ``TestBypassErrorIsNotAnInternalFailure`` below.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from mcp_server.core import write_gate
from mcp_server.handlers.remember import handler
from mcp_server.handlers.remember_helpers import (
    _grade_content_best_effort,
    _compute_gate_decision,
)


class TestDeliberateNeverNoveltyRejected:
    """Regression (1): a resolved ``deliberate`` write must never be
    rejected by the novelty gate, per the tool's documented contract."""

    def test_determine_bypass_bypasses_plain_deliberate_content(self):
        bypassed, reason = write_gate.determine_bypass(
            force=False,
            content="A routine, low-signal note with nothing special in it.",
            tags=[],
            write_class="deliberate",
        )
        assert bypassed is True
        assert reason == "bypass_write_class_deliberate"

    def test_determine_bypass_still_prefers_specific_content_reason(self):
        """Deliberate is checked LAST — a more specific content-based
        bypass reason (error/decision/tag) still wins when it applies, so
        existing diagnostics are not masked by the generic deliberate
        reason."""
        bypassed, reason = write_gate.determine_bypass(
            force=False,
            content="An exception occurred during startup",
            tags=[],
            write_class="deliberate",
        )
        assert bypassed is True
        assert reason == "bypass_error"

    def test_non_deliberate_write_class_unaffected(self):
        """auto/derived/mechanical classes still go through normal novelty
        gating — only ``deliberate`` gets the blanket bypass."""
        bypassed, reason = write_gate.determine_bypass(
            force=False,
            content="Plain content, no special keywords.",
            tags=[],
            write_class="auto",
        )
        assert bypassed is False
        assert reason is None

    def test_low_novelty_score_still_stores_for_deliberate(self):
        """End-to-end through _compute_gate_decision: a novelty score well
        below threshold must not produce a reject verdict when write_class
        resolves to deliberate."""
        should_store, gate_reason, _threshold = _compute_gate_decision(
            score=0.01,  # far below the default 0.4 threshold
            force=False,
            content="Low novelty deliberate content with nothing distinctive.",
            tags=[],
            domain="",
            write_class="deliberate",
        )
        assert should_store is True
        assert gate_reason == "bypass_write_class_deliberate"

    def test_handler_stores_low_novelty_deliberate_write_without_force(self):
        """Full handler round-trip (issue repro): a plain, non-forced
        write_class='deliberate' call must be stored, never
        below_threshold-rejected."""
        result = asyncio.run(
            handler(
                {
                    "content": (
                        "issue-147 regression: a low-novelty deliberate "
                        "write must still be stored, never gate-rejected."
                    ),
                    "write_class": "deliberate",
                }
            )
        )
        assert result["stored"] is True
        assert result["reason"] != "below_threshold"

    def test_handler_stores_low_novelty_write_with_omitted_write_class(self):
        """Omitting write_class falls back to deliberate (source-based
        inference, core.write_class.classify_write_class) and must get the
        same never-rejected treatment."""
        result = asyncio.run(
            handler(
                {
                    "content": (
                        "issue-147 regression: omitted write_class also "
                        "resolves to deliberate and must never be "
                        "below_threshold-rejected."
                    ),
                }
            )
        )
        assert result["stored"] is True
        assert result["reason"] != "below_threshold"


class TestGradingNeverBlocksTheWrite:
    """Regression (2): a missing/removed process cwd must never surface as
    a bare FileNotFoundError that blocks the write."""

    def test_grade_content_best_effort_survives_missing_cwd(self):
        """Direct unit test of the wrapper: os.getcwd() raising
        FileNotFoundError (as it does when the process cwd has been
        removed) must degrade to an UNVERIFIABLE report, never raise."""
        with patch(
            "os.getcwd", side_effect=FileNotFoundError(2, "No such file or directory")
        ):
            ctx = _grade_content_best_effort("plain content", directory="")
        assert ctx.report.grade == "unverifiable"
        assert ctx.grading_error == "FileNotFoundError"

    def test_grade_content_best_effort_passes_through_on_success(self, tmp_path):
        ctx = _grade_content_best_effort(
            "plain content with no refs", directory=str(tmp_path)
        )
        assert ctx.grading_error is None
        assert ctx.report.grade == "unverifiable"
        assert ctx.resolution_root == str(tmp_path)
        assert ctx.resolution_root_explicit is True
        assert ctx.resolution_root_exists is True

    def test_force_write_survives_missing_cwd(self):
        """End-to-end (issue repro): a force=True write must still insert
        even when the process cwd has been removed mid-session."""
        with patch(
            "os.getcwd", side_effect=FileNotFoundError(2, "No such file or directory")
        ):
            result = asyncio.run(
                handler(
                    {
                        "content": (
                            "issue-147 regression: force write must survive "
                            "a missing process cwd."
                        ),
                        "force": True,
                        # directory omitted so grade_from_content's
                        # base_dir=directory or os.getcwd() fallback fires.
                    }
                )
            )
        assert result["stored"] is True
        assert result["reason"] == "forced"
        assert result["provenance"]["grade"] == "unverifiable"

    def test_force_write_tags_grading_failure_observably(self):
        """The grading failure must be surfaced as a tag on the row, not
        silently absorbed (coding-standards.md: no silent fallbacks)."""
        from mcp_server.infrastructure.memory_config import get_memory_settings
        from mcp_server.infrastructure.memory_store import get_shared_store

        with patch(
            "os.getcwd", side_effect=FileNotFoundError(2, "No such file or directory")
        ):
            result = asyncio.run(
                handler(
                    {
                        "content": (
                            "issue-147 regression: grading failure must be "
                            "tagged on the stored row."
                        ),
                        "force": True,
                    }
                )
            )
        assert result["stored"] is True
        settings = get_memory_settings()
        store = get_shared_store(settings.DB_PATH, settings.EMBEDDING_DIM)
        row = store.get_memory(result["memory_id"])
        tags = row.get("tags") or []
        if isinstance(tags, str):
            import json as _json

            tags = _json.loads(tags)
        assert any(t.startswith("prov-grading-failed:") for t in tags)


class TestBypassErrorIsNotAnInternalFailure:
    """Regression (3, non-bug confirmation): ``reason: "bypass_error"`` on
    a SUCCESSFUL store is a legitimate, by-design content-based bypass
    (error/exception-shaped content), not evidence of an internal
    exception. Pinned here so a future "fix" doesn't rename/remove it."""

    def test_error_shaped_content_bypasses_with_reason_bypass_error(self):
        result = asyncio.run(
            handler(
                {
                    "content": (
                        "Fixed the connection exception that crashed the "
                        "worker at startup."
                    ),
                }
            )
        )
        assert result["stored"] is True
        assert result["reason"] == "bypass_error"


class TestNoMisleadingDatabaseUrlHintOnNonDbErrors:
    """The tool_error_handler DATABASE_URL hint must not be appended to
    unclassified, non-DB exception types (issue #147 point (d))."""

    def test_filenotfound_gets_no_database_hint(self):
        from mcp_server.tool_error_handler import _classify_error

        exc = FileNotFoundError(2, "No such file or directory")
        error_type, message = _classify_error(exc)
        assert error_type == "FileNotFoundError"
        # _classify_error itself never appends the hint — that happens in
        # safe_handler's except block, which now unconditionally omits it
        # for unclassified error types. Assert the classification is the
        # raw, un-hinted exception type/message.
        assert "DATABASE_URL" not in message

    @pytest.mark.asyncio
    async def test_safe_handler_omits_hint_for_filenotfounderror(self):
        from mcp.server.mcpserver.exceptions import ToolError
        from mcp_server.tool_error_handler import safe_handler

        async def failing_handler(_args):
            raise FileNotFoundError(2, "No such file or directory")

        with pytest.raises(ToolError) as exc_info:
            await safe_handler(failing_handler, {})

        assert "DATABASE_URL" not in str(exc_info.value)
        assert "FileNotFoundError" in str(exc_info.value)
