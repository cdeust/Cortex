"""Tests for mcp_server.handlers.remember — store memory handler."""

import asyncio

from mcp_server.handlers.remember import handler


class TestRememberHandler:
    def test_no_content_returns_not_stored(self):
        result = asyncio.run(handler(None))
        assert result["stored"] is False
        assert result["reason"] == "no_content"

    def test_empty_content_returns_not_stored(self):
        result = asyncio.run(handler({"content": ""}))
        assert result["stored"] is False

    def test_store_with_force(self):
        result = asyncio.run(
            handler(
                {
                    "content": "Force stored memory for testing",
                    "force": True,
                    "tags": ["test"],
                }
            )
        )
        assert result["stored"] is True
        assert result["memory_id"] > 0
        assert result["reason"] == "forced"
        assert "heat" in result
        assert "novelty" in result
        assert "importance" in result

    def test_error_content_bypasses_gate(self):
        result = asyncio.run(
            handler(
                {
                    "content": "RuntimeError: connection refused. The server crashed with a traceback.",
                }
            )
        )
        assert result["stored"] is True
        assert result["reason"] == "bypass_error"

    def test_decision_content_bypasses_gate(self):
        result = asyncio.run(
            handler(
                {
                    "content": "We decided to migrate from MySQL to PostgreSQL for the new project.",
                }
            )
        )
        assert result["stored"] is True
        assert result["reason"] == "bypass_decision"

    def test_important_tag_bypasses_gate(self):
        result = asyncio.run(
            handler(
                {
                    "content": "Something mildly interesting happened today",
                    "tags": ["important"],
                }
            )
        )
        assert result["stored"] is True
        assert result["reason"] == "bypass_important_tag"

    def test_prospective_triggers_extracted(self):
        result = asyncio.run(
            handler(
                {
                    "content": "TODO: fix the parser before release. Remember to update docs.",
                    "force": True,
                }
            )
        )
        assert result["stored"] is True
        assert len(result["triggers_created"]) >= 1

    def test_domain_auto_detection(self):
        result = asyncio.run(
            handler(
                {
                    "content": "Important architecture decision for the project",
                    "directory": "/tmp/fake-project",
                    "force": True,
                }
            )
        )
        assert result["stored"] is True
        # domain may be empty if no profile exists, but shouldn't error
        assert "domain" in result

    def test_response_shape(self):
        result = asyncio.run(
            handler(
                {
                    "content": "Shape test content with error keyword to ensure storage",
                    "force": True,
                }
            )
        )
        assert isinstance(result["stored"], bool)
        if result["stored"]:
            assert isinstance(result["memory_id"], int)
            assert isinstance(result["heat"], float)
            assert isinstance(result["novelty"], dict)
            assert isinstance(result["importance"], float)
            assert isinstance(result["valence"], float)
            assert isinstance(result["reason"], str)
            assert isinstance(result["triggers_created"], list)
