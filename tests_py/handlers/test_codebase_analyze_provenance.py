"""Tests for codebase_analyze's ADR-0052 sec 2 provenance wiring (INC5.2):
the src:native tag on every memory it writes, and the explicit
fallback_status marker so a run made while AP is reachable is never
silent about violating ingestion precedence.
"""

from __future__ import annotations

import pytest

from mcp_server.handlers import codebase_analyze as ca
from mcp_server.handlers import ingest_provenance as ip

# ingest_provenance binds the probe at module top (#197 family 4), so the
# patch targets the consumer's binding, not the defining module.
_UPSTREAM_AVAILABLE_PATH = (
    "mcp_server.handlers.ingest_provenance.codebase_upstream_available"
)


class _FakeAnalysis:
    def __init__(self):
        self.content_hash = "deadbeef"
        self.language = "python"
        self.definitions = []


class TestBuildTagsCarriesNativeProvenance:
    def test_includes_native_provenance_tag(self):
        tags = ca._build_tags("src/a.py", _FakeAnalysis())
        assert ip.SRC_NATIVE_TAG in tags

    def test_native_tag_alongside_existing_tags(self):
        tags = ca._build_tags("src/a.py", _FakeAnalysis())
        assert ca.CODEBASE_TAG in tags
        assert f"{ca.FILE_TAG_PREFIX}src/a.py" in tags
        assert ip.SRC_NATIVE_TAG in tags


class TestFallbackStatusInResponse:
    @pytest.mark.asyncio
    async def test_dry_run_reports_legitimate_fallback_when_ap_unreachable(
        self, tmp_path, monkeypatch
    ):
        (tmp_path / "a.py").write_text("x = 1\n")
        monkeypatch.setattr(_UPSTREAM_AVAILABLE_PATH, lambda: False)

        result = await ca.handler({"directory": str(tmp_path), "dry_run": True})

        assert result["fallback_status"] == ip.FALLBACK_LEGITIMATE_TAG

    @pytest.mark.asyncio
    async def test_dry_run_reports_precedence_violation_when_ap_reachable(
        self, tmp_path, monkeypatch
    ):
        (tmp_path / "a.py").write_text("x = 1\n")
        monkeypatch.setattr(_UPSTREAM_AVAILABLE_PATH, lambda: True)

        result = await ca.handler({"directory": str(tmp_path), "dry_run": True})

        assert result["fallback_status"] == ip.FALLBACK_PRECEDENCE_VIOLATION_TAG

    @pytest.mark.asyncio
    async def test_missing_directory_short_circuits_before_fallback_check(
        self, tmp_path
    ):
        result = await ca.handler({"directory": str(tmp_path / "does-not-exist")})
        assert result["analyzed"] is False
        assert "fallback_status" not in result
