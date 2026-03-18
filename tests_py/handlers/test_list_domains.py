"""Tests for mcp_server.handlers.list_domains — ported from list-domains.test.js."""

import asyncio

from mcp_server.handlers.list_domains import handler


class TestListDomainsHandler:
    def test_returns_domains_array_and_total(self):
        result = asyncio.run(handler())
        assert result is not None
        assert "domains" in result
        assert isinstance(result["domains"], list)
        assert "totalDomains" in result
        assert isinstance(result["totalDomains"], (int, float))
        assert result["totalDomains"] == len(result["domains"])

    def test_includes_global_style(self):
        result = asyncio.run(handler())
        assert "globalStyle" in result

    def test_domain_entries_shape(self):
        result = asyncio.run(handler())
        for domain in result["domains"]:
            assert "id" in domain
            assert "label" in domain
            assert "sessionCount" in domain
            assert isinstance(domain["sessionCount"], (int, float))
