"""Tests for mcp_server.handlers.detect_domain — ported from detect-domain.test.js."""

import asyncio

from mcp_server.handlers.detect_domain import handler


class TestDetectDomainHandler:
    def test_returns_result_no_args(self):
        result = asyncio.run(handler())
        assert result is not None
        assert "domain" in result or "coldStart" in result

    def test_returns_result_with_cwd(self):
        result = asyncio.run(handler({"cwd": "/tmp/some-project"}))
        assert result is not None

    def test_returns_result_with_first_message(self):
        result = asyncio.run(handler({"first_message": "help me refactor this module"}))
        assert result is not None
