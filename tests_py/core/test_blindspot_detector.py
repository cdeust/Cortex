"""Tests for mcp_server.core.blindspot_detector — ported from blindspot-detector.test.js."""

from mcp_server.core.blindspot_detector import detect_blind_spots


def _make_conv(**overrides):
    base = {
        "toolsUsed": [],
        "categories": [],
        "allText": "",
        "firstMessage": "",
        "duration": 0,
        "durationMinutes": 0,
    }
    base.update(overrides)
    return base


def _make_profiles(domains=None):
    return {"domains": domains or {}}


class TestDetectBlindSpots:
    def test_empty_conversations(self):
        assert detect_blind_spots("d", [], [], _make_profiles()) == []

    def test_category_blind_spots(self):
        domain_convs = [_make_conv(categories=["bug-fix"]) for _ in range(100)]
        result = detect_blind_spots("d", domain_convs, domain_convs, _make_profiles())
        cat_bs = [b for b in result if b["type"] == "category"]
        assert len(cat_bs) > 0
        for bs in cat_bs:
            assert bs["value"] != "bug-fix"
            assert "5%" in bs["description"]
            assert bs["suggestion"]
            assert bs["severity"] in ("high", "medium", "low")

    def test_high_severity_at_zero_percent(self):
        domain_convs = [_make_conv(categories=["feature"]) for _ in range(200)]
        result = detect_blind_spots("d", domain_convs, domain_convs, _make_profiles())
        cat_bs = [b for b in result if b["type"] == "category"]
        high = [b for b in cat_bs if b["severity"] == "high"]
        assert len(high) > 0

    def test_tool_blind_spots_relevant(self):
        domain_convs = [
            _make_conv(categories=["bug-fix", "debug"], toolsUsed=["Edit", "Write"])
            for _ in range(50)
        ]
        result = detect_blind_spots("d", domain_convs, domain_convs, _make_profiles())
        tool_bs = [b for b in result if b["type"] == "tool"]
        grep_bs = next((b for b in tool_bs if b["value"] == "Grep"), None)
        assert grep_bs is not None
        assert "Grep" in grep_bs["description"]
        assert "Grep" in grep_bs["suggestion"]

    def test_irrelevant_tools_not_flagged(self):
        domain_convs = [
            _make_conv(categories=["deployment"], toolsUsed=["Bash"]) for _ in range(50)
        ]
        result = detect_blind_spots("d", domain_convs, domain_convs, _make_profiles())
        tool_bs = [b for b in result if b["type"] == "tool"]
        web_fetch_bs = next((b for b in tool_bs if b["value"] == "WebFetch"), None)
        assert web_fetch_bs is None

    def test_tools_above_threshold_not_flagged(self):
        domain_convs = [
            _make_conv(
                categories=["bug-fix"],
                toolsUsed=["Grep", "Edit"] if i == 0 else ["Edit"],
            )
            for i in range(20)
        ]
        result = detect_blind_spots("d", domain_convs, domain_convs, _make_profiles())
        grep_bs = [b for b in result if b["type"] == "tool" and b["value"] == "Grep"]
        assert len(grep_bs) == 0

    def test_exploration_pattern_blind_spot(self):
        domain_convs = [_make_conv(categories=["bug-fix"]) for _ in range(20)]
        all_convs = domain_convs + [
            _make_conv(categories=["research"]) for _ in range(20)
        ]
        result = detect_blind_spots("d", domain_convs, all_convs, _make_profiles())
        exp_bs = next(
            (
                b
                for b in result
                if b["type"] == "pattern" and b["value"] == "exploration"
            ),
            None,
        )
        assert exp_bs is not None
        assert exp_bs["severity"] == "high"

    def test_deep_work_pattern_blind_spot(self):
        domain_convs = [
            _make_conv(categories=["bug-fix"], duration=5, durationMinutes=5)
            for _ in range(20)
        ]
        all_convs = domain_convs + [
            _make_conv(categories=["research"], duration=45, durationMinutes=45)
            for _ in range(20)
        ]
        result = detect_blind_spots("d", domain_convs, all_convs, _make_profiles())
        deep_bs = next(
            (b for b in result if b["type"] == "pattern" and b["value"] == "deep-work"),
            None,
        )
        assert deep_bs is not None

    def test_quick_iteration_pattern_blind_spot(self):
        domain_convs = [
            _make_conv(categories=["architecture"], duration=45, durationMinutes=45)
            for _ in range(20)
        ]
        all_convs = domain_convs + [
            _make_conv(categories=["bug-fix"], duration=5, durationMinutes=5)
            for _ in range(20)
        ]
        result = detect_blind_spots("d", domain_convs, all_convs, _make_profiles())
        quick_bs = next(
            (
                b
                for b in result
                if b["type"] == "pattern" and b["value"] == "quick-iteration"
            ),
            None,
        )
        assert quick_bs is not None
        assert quick_bs["severity"] == "low"

    def test_no_pattern_blind_spots_when_balanced(self):
        convs = [
            _make_conv(
                categories=["bug-fix"] if i % 2 == 0 else ["research"],
                duration=5 if i % 2 == 0 else 45,
                durationMinutes=5 if i % 2 == 0 else 45,
            )
            for i in range(20)
        ]
        result = detect_blind_spots("d", convs, convs, _make_profiles())
        exp_bs = next(
            (
                b
                for b in result
                if b["type"] == "pattern" and b["value"] == "exploration"
            ),
            None,
        )
        assert exp_bs is None

    def test_categorize_fallback(self):
        domain_convs = [
            _make_conv(
                allText="fix the bug in the broken code crash error", toolsUsed=["Edit"]
            )
            for _ in range(50)
        ]
        result = detect_blind_spots("d", domain_convs, domain_convs, _make_profiles())
        assert isinstance(result, list)

    def test_all_blind_spots_have_required_fields(self):
        domain_convs = [_make_conv(categories=["feature"]) for _ in range(100)]
        result = detect_blind_spots("d", domain_convs, domain_convs, _make_profiles())
        for bs in result:
            assert bs["type"]
            assert bs["value"]
            assert bs["severity"]
            assert bs["description"]
            assert bs["suggestion"]
            assert bs["severity"] in ("high", "medium", "low")
