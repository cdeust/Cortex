"""Direct tests for mcp_server.core.context_assembly.warning (#196)."""

from __future__ import annotations

from mcp_server.core.context_assembly.budget import AssemblyMetrics
from mcp_server.core.context_assembly.warning import build_truncation_banner


class TestBuildTruncationBanner:
    def test_no_reduction_returns_empty_string(self):
        metrics = AssemblyMetrics(
            original_tokens={"{{A}}": 100}, final_tokens={"{{A}}": 100}
        )
        assert build_truncation_banner(metrics) == ""

    def test_zero_original_tokens_placeholder_skipped(self):
        # A placeholder with original_tokens <= 0 (e.g. an empty section)
        # must never appear in the banner, regardless of final_tokens.
        metrics = AssemblyMetrics(
            original_tokens={"{{EMPTY}}": 0}, final_tokens={"{{EMPTY}}": 0}
        )
        assert build_truncation_banner(metrics) == ""

    def test_material_reduction_produces_banner(self):
        metrics = AssemblyMetrics(
            original_tokens={"{{A}}": 100}, final_tokens={"{{A}}": 10}
        )
        banner = build_truncation_banner(metrics)
        assert "TRUNCATION WARNING" in banner
        assert "{{A}}" in banner
        assert "10%" in banner

    def test_reduction_below_threshold_not_flagged(self):
        metrics = AssemblyMetrics(
            original_tokens={"{{A}}": 100}, final_tokens={"{{A}}": 95}
        )
        assert build_truncation_banner(metrics) == ""

    def test_custom_threshold(self):
        metrics = AssemblyMetrics(
            original_tokens={"{{A}}": 100}, final_tokens={"{{A}}": 95}
        )
        banner = build_truncation_banner(metrics, reduction_threshold=0.99)
        assert "TRUNCATION WARNING" in banner
