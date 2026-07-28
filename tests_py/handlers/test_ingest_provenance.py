"""Tests for ingest_provenance — ADR-0052 sec 2 (INC5.2).

Covers: provenance tag builders (src:ap / src:native), the fallback-
precedence marker for codebase_analyze, both AP-version fetchers (bridge
path vs pool path), and the version-parity comparison (match / mismatch /
unknown — never a false mismatch on partial failure).
"""

from __future__ import annotations

import pytest

from mcp_server.handlers import ingest_provenance as ip


def _const_async(value):
    async def _f(*_args, **_kwargs):
        return value

    return _f


class TestProvenanceTags:
    def test_ap_provenance_tags_with_version(self):
        assert ip.ap_provenance_tags("0.6.0") == ["src:ap", "src:ap-version:0.6.0"]

    def test_ap_provenance_tags_without_version(self):
        assert ip.ap_provenance_tags(None) == ["src:ap"]

    def test_ap_provenance_tags_empty_string_version_omitted(self):
        # An empty string is a falsy "no version resolved", not a version.
        assert ip.ap_provenance_tags("") == ["src:ap"]

    def test_native_provenance_tags(self):
        assert ip.native_provenance_tags() == ["src:native"]

    def test_ap_version_tag(self):
        assert ip.ap_version_tag("0.4.0") == "src:ap-version:0.4.0"


class TestNativeFallbackStatus:
    def test_legitimate_when_ap_unreachable(self, monkeypatch):
        # Patch the consumer's binding (top-level import, #197 family 4).
        monkeypatch.setattr(
            ip,
            "codebase_upstream_available",
            lambda: False,
        )
        tag, warning = ip.native_fallback_status()
        assert tag == ip.FALLBACK_LEGITIMATE_TAG
        assert warning is None

    def test_precedence_violation_when_ap_reachable(self, monkeypatch):
        # Patch the consumer's binding (top-level import, #197 family 4).
        monkeypatch.setattr(
            ip,
            "codebase_upstream_available",
            lambda: True,
        )
        tag, warning = ip.native_fallback_status()
        assert tag == ip.FALLBACK_PRECEDENCE_VIOLATION_TAG
        assert warning is not None
        assert "ADR-0052" in warning


class TestFetchApVersionViaBridge:
    @pytest.mark.asyncio
    async def test_extracts_version(self, monkeypatch):
        class _FakeBridge:
            async def health_check(self):
                return {"version": "0.5.0"}

            async def close(self):
                return None

        monkeypatch.setattr(ip, "APBridge", lambda: _FakeBridge())
        assert await ip.fetch_ap_version_via_bridge() == "0.5.0"

    @pytest.mark.asyncio
    async def test_none_when_bridge_disabled(self, monkeypatch):
        class _FakeBridge:
            async def health_check(self):
                return None  # APBridge.call() returns None when unavailable

            async def close(self):
                return None

        monkeypatch.setattr(ip, "APBridge", lambda: _FakeBridge())
        assert await ip.fetch_ap_version_via_bridge() is None

    @pytest.mark.asyncio
    async def test_none_on_exception_never_raises(self, monkeypatch):
        class _FakeBridge:
            async def health_check(self):
                raise RuntimeError("boom")

            async def close(self):
                return None

        monkeypatch.setattr(ip, "APBridge", lambda: _FakeBridge())
        assert await ip.fetch_ap_version_via_bridge() is None

    @pytest.mark.asyncio
    async def test_none_on_missing_version_key(self, monkeypatch):
        class _FakeBridge:
            async def health_check(self):
                return {"status": "ok"}  # malformed / older server, no version

            async def close(self):
                return None

        monkeypatch.setattr(ip, "APBridge", lambda: _FakeBridge())
        assert await ip.fetch_ap_version_via_bridge() is None


class TestFetchApVersionViaPool:
    @pytest.mark.asyncio
    async def test_extracts_version(self, monkeypatch):
        async def _call(server, tool, args):
            assert server == "codebase"
            assert tool == "health_check"
            return {"version": "0.4.0"}

        monkeypatch.setattr(ip, "call_upstream", _call)
        assert await ip.fetch_ap_version_via_pool() == "0.4.0"

    @pytest.mark.asyncio
    async def test_none_on_connection_error_never_raises(self, monkeypatch):
        async def _call(server, tool, args):
            raise ConnectionError("codebase server unreachable")

        monkeypatch.setattr(ip, "call_upstream", _call)
        assert await ip.fetch_ap_version_via_pool() is None

    @pytest.mark.asyncio
    async def test_none_on_malformed_payload(self, monkeypatch):
        async def _call(server, tool, args):
            return {"no_version_key": True}

        monkeypatch.setattr(ip, "call_upstream", _call)
        assert await ip.fetch_ap_version_via_pool() is None


class TestCheckVersionParity:
    @pytest.mark.asyncio
    async def test_match_when_both_paths_agree(self, monkeypatch):
        monkeypatch.setattr(ip, "fetch_ap_version_via_bridge", _const_async("0.5.0"))
        monkeypatch.setattr(ip, "fetch_ap_version_via_pool", _const_async("0.5.0"))
        result = await ip.check_version_parity()
        assert result.status == "match"
        assert result.warning is None
        assert result.bridge_version == result.pool_version == "0.5.0"

    @pytest.mark.asyncio
    async def test_mismatch_when_paths_disagree_and_logs_warning(
        self, monkeypatch, caplog
    ):
        # Reproduces the observed skew: symlinked binary vs manifest plugin
        # (iface angle-mort 5).
        monkeypatch.setattr(ip, "fetch_ap_version_via_bridge", _const_async("0.6.0"))
        monkeypatch.setattr(ip, "fetch_ap_version_via_pool", _const_async("0.4.0"))
        with caplog.at_level("WARNING", logger="mcp_server.handlers.ingest_provenance"):
            result = await ip.check_version_parity()
        assert result.status == "mismatch"
        assert result.bridge_version == "0.6.0"
        assert result.pool_version == "0.4.0"
        assert "0.6.0" in result.warning and "0.4.0" in result.warning
        assert "ADR-0052" in result.warning
        assert any("skew" in rec.message for rec in caplog.records)

    @pytest.mark.asyncio
    async def test_unknown_never_false_mismatch_when_bridge_unreachable(
        self, monkeypatch, caplog
    ):
        monkeypatch.setattr(ip, "fetch_ap_version_via_bridge", _const_async(None))
        monkeypatch.setattr(ip, "fetch_ap_version_via_pool", _const_async("0.4.0"))
        with caplog.at_level("WARNING", logger="mcp_server.handlers.ingest_provenance"):
            result = await ip.check_version_parity()
        assert result.status == "unknown"
        assert result.warning is not None
        # unknown is not a mismatch — no warning-level log for it.
        assert not any("skew" in rec.message for rec in caplog.records)

    @pytest.mark.asyncio
    async def test_unknown_when_pool_unreachable(self, monkeypatch):
        monkeypatch.setattr(ip, "fetch_ap_version_via_bridge", _const_async("0.4.0"))
        monkeypatch.setattr(ip, "fetch_ap_version_via_pool", _const_async(None))
        result = await ip.check_version_parity()
        assert result.status == "unknown"

    @pytest.mark.asyncio
    async def test_unknown_when_both_unreachable(self, monkeypatch):
        monkeypatch.setattr(ip, "fetch_ap_version_via_bridge", _const_async(None))
        monkeypatch.setattr(ip, "fetch_ap_version_via_pool", _const_async(None))
        result = await ip.check_version_parity()
        assert result.status == "unknown"
        assert result.bridge_version is None
        assert result.pool_version is None
