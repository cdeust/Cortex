"""E8 — wiki sync errors must be surfaced, not silently swallowed.

Prior behaviour (pre-Phase-1): ``wiki_store.sync_memory`` swallowed every
exception and returned None. A failing disk, a path-traversal exception,
or a classifier bug all looked identical to "classifier rejected the
memory" — the worst-of-both silent failure Taleb flags.

New behaviour:
  - ``sync_memory_strict`` raises on I/O errors (callers can observe).
  - ``sync_memory`` remains as a swallowing wrapper for legacy callers.
  - The ``remember`` handler calls ``sync_memory_strict`` and, on failure,
    emits a ``warnings`` entry in the response instead of silently
    dropping the signal.

Two scenarios covered:
  1. Direct test of ``sync_memory_strict`` — it raises on underlying error.
  2. Integration test through the ``remember`` handler — the handler
     surfaces the error as a ``warnings`` list entry.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from mcp_server.handlers.remember import handler as remember_handler
from mcp_server.infrastructure import wiki_store


class TestSyncMemoryStrict:
    """Direct tests of the strict variant."""

    def test_raises_on_write_error(self, tmp_path):
        """An I/O failure in write_page propagates out of sync_memory_strict."""
        # Force build_from_memory to return a result that triggers a write.
        with patch(
            "mcp_server.infrastructure.wiki_store.build_from_memory",
            return_value=("notes/test.md", "# Test\nBody."),
        ):
            with patch(
                "mcp_server.infrastructure.wiki_store.write_page",
                side_effect=OSError("disk full"),
            ):
                with pytest.raises(OSError, match="disk full"):
                    wiki_store.sync_memory_strict(
                        tmp_path,
                        memory_id=1,
                        content="some decision",
                        tags=["decision"],
                        domain="cortex",
                    )

    def test_returns_none_on_classifier_rejection(self, tmp_path):
        """build_from_memory returning None is not an error, not a raise."""
        with patch(
            "mcp_server.infrastructure.wiki_store.build_from_memory",
            return_value=None,
        ):
            result = wiki_store.sync_memory_strict(
                tmp_path,
                memory_id=1,
                content="noise",
                tags=[],
                domain="",
            )
            assert result is None

    def test_returns_path_on_success(self, tmp_path):
        """Successful write returns the relative path."""
        with patch(
            "mcp_server.infrastructure.wiki_store.build_from_memory",
            return_value=("notes/ok.md", "# OK\nBody."),
        ):
            result = wiki_store.sync_memory_strict(
                tmp_path,
                memory_id=1,
                content="decision",
                tags=["decision"],
                domain="cortex",
            )
            assert result == "notes/ok.md"
            assert (tmp_path / "notes" / "ok.md").exists()


class TestSyncMemoryLegacyWrapper:
    """The legacy swallowing wrapper still exists for backwards compat."""

    def test_returns_none_on_error(self, tmp_path):
        with patch(
            "mcp_server.infrastructure.wiki_store.build_from_memory",
            return_value=("notes/x.md", "# X\nB."),
        ):
            with patch(
                "mcp_server.infrastructure.wiki_store.write_page",
                side_effect=OSError("disk full"),
            ):
                # Legacy wrapper swallows → None.
                result = wiki_store.sync_memory(
                    tmp_path,
                    memory_id=1,
                    content="some decision",
                    tags=["decision"],
                    domain="cortex",
                )
                assert result is None


class TestRememberHandlerSurfacesWikiErrors:
    """Integration: remember() captures wiki-sync failures into warnings."""

    def test_wiki_error_surfaced_as_warning(self):
        """Force sync_memory_strict to raise → handler adds a warnings entry.

        The memory is stored regardless (wiki sync is post-write), so
        ``result["stored"]`` stays True but ``result["warnings"]`` carries
        the error signal.
        """
        with patch(
            "mcp_server.handlers.remember.wiki_store.sync_memory_strict",
            side_effect=RuntimeError("wiki write failed"),
        ):
            result = asyncio.run(
                remember_handler(
                    {
                        "content": (
                            "We decided to adopt pgvector HNSW over IVFFlat "
                            "for 3x faster ANN lookups."
                        ),
                        "force": True,
                        "tags": ["decision"],
                    }
                )
            )

        assert result["stored"] is True, "memory must still be stored"
        assert "warnings" in result, "wiki failure must be surfaced"
        wiki_warnings = [
            w for w in result["warnings"] if w.get("scope") == "wiki_sync"
        ]
        assert len(wiki_warnings) == 1
        w = wiki_warnings[0]
        assert w["error_type"] == "RuntimeError"
        assert "wiki write failed" in w["message"]
        assert w["memory_id"] == result["memory_id"]

    def test_no_warning_when_wiki_rejects_or_succeeds(self):
        """Classifier rejection (None return) must NOT produce a warning."""
        with patch(
            "mcp_server.handlers.remember.wiki_store.sync_memory_strict",
            return_value=None,
        ):
            result = asyncio.run(
                remember_handler(
                    {
                        "content": (
                            "We decided to adopt pgvector HNSW over IVFFlat "
                            "for 3x faster ANN lookups."
                        ),
                        "force": True,
                        "tags": ["decision"],
                    }
                )
            )

        assert result["stored"] is True
        # No wiki-sync warning: rejection is not a failure.
        wiki_warnings = [
            w for w in result.get("warnings", []) if w.get("scope") == "wiki_sync"
        ]
        assert wiki_warnings == []
