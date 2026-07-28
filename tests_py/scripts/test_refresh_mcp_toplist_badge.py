"""Tests for scripts/refresh_mcp_toplist_badge.py — badge refresh gate.

Written unittest-style to match the sibling script gates; Cortex's pytest
collects unittest classes natively.

The property under test throughout is FAIL CLOSED: a figure that cannot be
validated must never reach the badge. A stale badge is a known cost of the
static-asset choice; a confidently wrong one would be a false public claim,
so every failure path below asserts the badge is left untouched.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
import urllib.error
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock
from xml.etree import ElementTree

_spec = importlib.util.spec_from_file_location(
    "refresh_mcp_toplist_badge",
    Path(__file__).resolve().parents[2] / "scripts" / "refresh_mcp_toplist_badge.py",
)
badge = importlib.util.module_from_spec(_spec)
# Register before exec: @dataclass resolves its owning module through
# sys.modules, which a spec-loaded module is otherwise absent from.
sys.modules[_spec.name] = badge
_spec.loader.exec_module(badge)

# The observed live figure, 2026-07-28.
LIVE_RANK, LIVE_TOTAL = 964, 81_919
LIVE_PAGE = (
    '<p class="x">Cortex is a Model Context Protocol (MCP) server published by '
    "cdeust. It ranks #964 of 81,919 servers tracked on MCP Toplist, and its "
    "repository has 68 GitHub stars.</p>"
)


class TestValidate(unittest.TestCase):
    def test_accepts_a_well_formed_figure(self):
        r = badge.validate(964, 81919, "t")
        self.assertEqual((r.rank, r.total, r.source), (964, 81919, "t"))

    def test_strips_thousands_separators_from_scraped_text(self):
        self.assertEqual(badge.validate("964", "81,919", "t").total, 81919)

    def test_rejects_non_numeric(self):
        with self.assertRaises(badge.UpstreamError):
            badge.validate("nine", "81,919", "t")

    def test_rejects_none(self):
        with self.assertRaises(badge.UpstreamError):
            badge.validate(None, 81919, "t")

    def test_rejects_zero_rank(self):
        # Rank is a 1-based position; 0 signals a parser that matched noise.
        with self.assertRaises(badge.UpstreamError):
            badge.validate(0, 81919, "t")

    def test_rejects_negative_rank(self):
        with self.assertRaises(badge.UpstreamError):
            badge.validate(-1, 81919, "t")

    def test_rejects_zero_total_before_it_divides(self):
        # Guards Ranking.percentile against ZeroDivisionError.
        with self.assertRaises(badge.UpstreamError):
            badge.validate(1, 0, "t")

    def test_rejects_rank_beyond_the_field(self):
        with self.assertRaises(badge.UpstreamError):
            badge.validate(81920, 81919, "t")

    def test_accepts_rank_equal_to_field_size(self):
        self.assertEqual(badge.validate(5, 5, "t").rank, 5)


class TestPercentileAndTier(unittest.TestCase):
    def test_live_figure_rounds_to_one_decimal(self):
        r = badge.validate(LIVE_RANK, LIVE_TOTAL, "t")
        self.assertAlmostEqual(r.percentile(), 1.2)
        self.assertEqual(r.tier_text(), "Top 1.2%")

    def test_very_high_rank_reports_a_bound_not_zero(self):
        # 1/81919 = 0.0012% would render "Top 0.0%", which reads as a bug.
        self.assertEqual(badge.validate(1, LIVE_TOTAL, "t").tier_text(), "Top <0.1%")

    def test_boundary_just_above_the_bound_uses_the_number(self):
        self.assertEqual(badge.validate(1, 1000, "t").tier_text(), "Top 0.1%")

    def test_last_place_is_one_hundred_percent(self):
        self.assertEqual(badge.validate(50, 50, "t").tier_text(), "Top 100.0%")


class TestParseLeaderboard(unittest.TestCase):
    def _payload(self, doc) -> bytes:
        return json.dumps(doc).encode()

    def test_dict_with_servers_and_explicit_total(self):
        doc = {
            "total": LIVE_TOTAL,
            "servers": [{"id": badge.SERVER_ID, "rank": LIVE_RANK}],
        }
        r = badge.parse_leaderboard(self._payload(doc))
        self.assertEqual((r.rank, r.total), (LIVE_RANK, LIVE_TOTAL))

    def test_bare_list_falls_back_to_list_length_for_total(self):
        doc = [{"id": "other", "rank": 1}, {"id": badge.SERVER_ID, "rank": 2}]
        self.assertEqual(badge.parse_leaderboard(self._payload(doc)).total, 2)

    def test_alternate_identity_and_rank_keys(self):
        doc = {"servers": [{"slug": badge.SERVER_ID, "position": 3}, {}, {}]}
        self.assertEqual(badge.parse_leaderboard(self._payload(doc)).rank, 3)

    def test_absent_server_raises(self):
        doc = {"servers": [{"id": "someone/else", "rank": 1}]}
        with self.assertRaises(badge.UpstreamError):
            badge.parse_leaderboard(self._payload(doc))

    def test_entry_without_a_rank_raises_rather_than_defaulting(self):
        doc = {"servers": [{"id": badge.SERVER_ID, "stars": 68}]}
        with self.assertRaises(badge.UpstreamError):
            badge.parse_leaderboard(self._payload(doc))

    def test_invalid_json_raises(self):
        with self.assertRaises(badge.UpstreamError):
            badge.parse_leaderboard(b"<html>503</html>")

    def test_empty_list_raises(self):
        with self.assertRaises(badge.UpstreamError):
            badge.parse_leaderboard(b"[]")

    def test_unrecognised_shape_is_refused_not_guessed(self):
        with self.assertRaises(badge.UpstreamError):
            badge.parse_leaderboard(self._payload({"data": {"rank": 964}}))

    def test_non_dict_entries_are_skipped_not_crashed_on(self):
        doc = {"servers": ["junk", None, {"id": badge.SERVER_ID, "rank": 3}]}
        self.assertEqual(badge.parse_leaderboard(self._payload(doc)).rank, 3)

    def test_rank_beyond_field_is_rejected_by_the_shared_validator(self):
        doc = {"total": 2, "servers": [{"id": badge.SERVER_ID, "rank": 99}]}
        with self.assertRaises(badge.UpstreamError):
            badge.parse_leaderboard(self._payload(doc))


class TestParseServerPage(unittest.TestCase):
    def test_extracts_both_numbers_from_the_live_sentence(self):
        r = badge.parse_server_page(LIVE_PAGE)
        self.assertEqual((r.rank, r.total), (LIVE_RANK, LIVE_TOTAL))

    def test_reworded_page_raises_rather_than_matching_loosely(self):
        # The failure mode this guards: a page that still says "#964"
        # somewhere but no longer pairs it with the field size.
        with self.assertRaises(badge.UpstreamError):
            badge.parse_server_page("<title>Cortex - MCP Server #964</title>")

    def test_empty_document_raises(self):
        with self.assertRaises(badge.UpstreamError):
            badge.parse_server_page("")

    def test_match_is_case_insensitive_and_whitespace_tolerant(self):
        r = badge.parse_server_page("It  Ranks  # 12  of  100  Servers  Tracked here")
        self.assertEqual((r.rank, r.total), (12, 100))


class TestRenderBadge(unittest.TestCase):
    def _svg(self, rank=LIVE_RANK, total=LIVE_TOTAL, day=date(2026, 7, 28)) -> str:
        return badge.render_badge(badge.validate(rank, total, "server page"), day)

    def test_output_is_well_formed_xml(self):
        ElementTree.fromstring(self._svg())

    def test_carries_the_tier_and_a_locale_independent_date(self):
        svg = self._svg()
        self.assertIn("Top 1.2% · Jul 2026", svg)

    def test_month_name_does_not_depend_on_runner_locale(self):
        self.assertIn("Mar 2027", self._svg(day=date(2027, 3, 1)))

    def test_records_its_own_provenance_for_the_next_maintainer(self):
        svg = self._svg()
        self.assertIn("964", svg)
        self.assertIn("81,919", svg)
        self.assertIn(badge.SERVER_PAGE_URL, svg)

    def test_claim_is_attributive_never_a_quality_assertion(self):
        # Upstream states its score is "not a quality assessment"; the badge
        # must not outrun that.
        svg = self._svg()
        self.assertIn("RANKED", svg)
        self.assertNotIn("best", svg.lower())

    def test_omits_constructs_githubs_svg_sanitizer_strips(self):
        svg = self._svg()
        self.assertNotIn("<style", svg)
        self.assertNotIn("@import", svg)
        self.assertNotIn("<script", svg)

    def test_references_no_remote_resource(self):
        # A remote reference would reintroduce the third-party beacon the
        # committed asset exists to avoid. The xmlns URI does not count: it
        # is an identifier, never dereferenced by a renderer.
        svg = self._svg()
        for construct in ("<image", "xlink:href", "href=", "url(http", "@import"):
            self.assertNotIn(construct, svg)
        self.assertEqual(
            svg.count("http"),
            svg.count('xmlns="http://www.w3.org/2000/svg"')
            + svg.count(badge.SERVER_PAGE_URL),
        )

    def test_every_text_run_is_pinned_with_textlength(self):
        # textLength is what makes an inaccurate width estimate cost
        # letter-spacing instead of overflow past the panel edge.
        svg = self._svg()
        self.assertEqual(svg.count("<text"), svg.count("textLength="))

    def test_panel_widths_sum_to_the_declared_canvas(self):
        svg = self._svg()
        root = ElementTree.fromstring(svg)
        total_w = float(root.get("width"))
        rects = [r for r in root.iter("{http://www.w3.org/2000/svg}rect")]
        panels = [
            r
            for r in rects
            if r.get("height") == "20" and r.get("fill") in ("#3b3129", "#a53e00")
        ]
        self.assertEqual(sum(float(r.get("width")) for r in panels), total_w)

    def test_wider_message_widens_the_canvas(self):
        narrow = ElementTree.fromstring(self._svg(rank=1, total=LIVE_TOTAL)).get(
            "width"
        )
        wide = ElementTree.fromstring(self._svg(rank=50, total=50)).get("width")
        self.assertGreater(float(wide), float(narrow))

    def test_reproduces_the_measured_reference_geometry(self):
        # The hand-built badge this generator replaced was 216x20 with a
        # 110px message run; the width model must not silently drift off it.
        root = ElementTree.fromstring(self._svg())
        self.assertEqual(root.get("width"), "216")


class TestFetch(unittest.TestCase):
    def test_http_error_becomes_an_upstream_error_naming_the_code(self):
        def opener(request, timeout=None):
            raise urllib.error.HTTPError(
                request.full_url, 503, "Service Unavailable", {}, None
            )

        with self.assertRaises(badge.UpstreamError) as ctx:
            badge.fetch("https://example.test/x", opener=opener)
        self.assertIn("503", str(ctx.exception))

    def test_unreachable_host_becomes_an_upstream_error(self):
        def opener(request, timeout=None):
            raise urllib.error.URLError("no route to host")

        with self.assertRaises(badge.UpstreamError):
            badge.fetch("https://example.test/x", opener=opener)

    def test_timeout_becomes_an_upstream_error(self):
        def opener(request, timeout=None):
            raise TimeoutError("timed out")

        with self.assertRaises(badge.UpstreamError):
            badge.fetch("https://example.test/x", opener=opener)


class TestResolveRanking(unittest.TestCase):
    def test_prefers_the_structured_export_when_it_works(self):
        doc = json.dumps(
            {"total": 10, "servers": [{"id": badge.SERVER_ID, "rank": 2}]}
        ).encode()
        ranking, notices = badge.resolve_ranking(lambda url: doc)
        self.assertEqual(ranking.source, "leaderboard.json")
        self.assertEqual(notices, [])

    def test_falls_back_to_the_page_and_reports_why(self):
        # The live condition as of 2026-07-28: leaderboard.json 503s.
        def fetch_fn(url):
            if url == badge.LEADERBOARD_URL:
                raise badge.UpstreamError("leaderboard.json: HTTP 503")
            return LIVE_PAGE.encode()

        ranking, notices = badge.resolve_ranking(fetch_fn)
        self.assertEqual(ranking.source, "server page")
        self.assertEqual(ranking.rank, LIVE_RANK)
        # The fallback must be announced, never silent.
        self.assertEqual(len(notices), 1)
        self.assertIn("503", notices[0])

    def test_both_paths_failing_raises_and_names_both(self):
        def fetch_fn(url):
            raise badge.UpstreamError(f"{url}: unreachable")

        with self.assertRaises(badge.UpstreamError) as ctx:
            badge.resolve_ranking(fetch_fn)
        message = str(ctx.exception)
        self.assertIn(badge.LEADERBOARD_URL, message)
        self.assertIn(badge.SERVER_PAGE_URL, message)

    def test_a_served_but_unparseable_export_still_falls_through(self):
        def fetch_fn(url):
            return (
                b"<html>maintenance</html>"
                if url == badge.LEADERBOARD_URL
                else LIVE_PAGE.encode()
            )

        ranking, notices = badge.resolve_ranking(fetch_fn)
        self.assertEqual(ranking.source, "server page")
        self.assertTrue(notices)


class TestMain(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.badge_path = Path(self._tmp.name) / "badge.svg"
        self.addCleanup(self._tmp.cleanup)

    def _patch_upstream(self, ranking=None, error=None):
        def fake_resolve(*_args, **_kwargs):
            if error is not None:
                raise error
            return ranking, []

        return mock.patch.object(badge, "resolve_ranking", fake_resolve)

    def _live_ranking(self):
        return badge.validate(LIVE_RANK, LIVE_TOTAL, "server page")

    def test_writes_the_badge_when_absent(self):
        with self._patch_upstream(self._live_ranking()):
            code = badge.main(["--badge", str(self.badge_path)])
        self.assertEqual(code, 0)
        self.assertIn("Top 1.2%", self.badge_path.read_text())

    def test_is_idempotent_when_already_current(self):
        with self._patch_upstream(self._live_ranking()):
            badge.main(["--badge", str(self.badge_path)])
            first = self.badge_path.read_text()
            code = badge.main(["--badge", str(self.badge_path)])
        self.assertEqual(code, 0)
        self.assertEqual(self.badge_path.read_text(), first)

    def test_check_mode_passes_on_a_current_badge(self):
        with self._patch_upstream(self._live_ranking()):
            badge.main(["--badge", str(self.badge_path)])
            code = badge.main(["--check", "--badge", str(self.badge_path)])
        self.assertEqual(code, 0)

    def test_check_mode_fails_on_a_stale_badge_without_writing(self):
        self.badge_path.write_text("<svg>stale</svg>")
        with self._patch_upstream(self._live_ranking()):
            code = badge.main(["--check", "--badge", str(self.badge_path)])
        self.assertEqual(code, 1)
        self.assertEqual(self.badge_path.read_text(), "<svg>stale</svg>")

    def test_upstream_failure_exits_nonzero_and_leaves_the_badge_untouched(self):
        # The central fail-closed guarantee: a broken upstream must never be
        # able to blank or corrupt a published claim.
        self.badge_path.write_text("<svg>previous</svg>")
        with self._patch_upstream(error=badge.UpstreamError("all sources down")):
            code = badge.main(["--badge", str(self.badge_path)])
        self.assertEqual(code, 1)
        self.assertEqual(self.badge_path.read_text(), "<svg>previous</svg>")

    def test_upstream_failure_does_not_create_a_badge_from_nothing(self):
        with self._patch_upstream(error=badge.UpstreamError("all sources down")):
            code = badge.main(["--badge", str(self.badge_path)])
        self.assertEqual(code, 1)
        self.assertFalse(self.badge_path.exists())


if __name__ == "__main__":
    unittest.main()
