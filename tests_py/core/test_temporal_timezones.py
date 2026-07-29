"""Tests for mcp_server.core.temporal_timezones — the RFC 5322 zone policy.

Every row of the cited table is asserted here rather than through
`normalize_date_to_iso`, because dateutil short-circuits some of them
(it hands `GMT`/`UTC`/`Z` over as a resolved offset of 0) and the table is a
transcription of RFC 5322 §4.3 that must stay faithful to its source
independently of which parser consumes it.
"""

import pytest

from mcp_server.core.temporal_timezones import (
    RFC5322_ZONE_NAMES,
    RFC5322ZoneResolver,
)

_HOUR = 3600

# source: RFC 5322 §4.3 (Resnick, 2008), obs-zone offsets, transcribed
# independently of the module under test.
_RFC5322_TABLE = [
    ("UT", 0),
    ("GMT", 0),
    ("EST", -5 * _HOUR),
    ("EDT", -4 * _HOUR),
    ("CST", -6 * _HOUR),
    ("CDT", -5 * _HOUR),
    ("MST", -7 * _HOUR),
    ("MDT", -6 * _HOUR),
    ("PST", -8 * _HOUR),
    ("PDT", -7 * _HOUR),
]


class TestResolvesTheCitedTable:
    @pytest.mark.parametrize(("name", "offset_seconds"), _RFC5322_TABLE)
    def test_each_rfc5322_row(self, name, offset_seconds):
        resolver = RFC5322ZoneResolver()
        assert resolver(name, None) == offset_seconds
        assert resolver.unresolved is None

    def test_abbreviation_is_case_insensitive(self):
        resolver = RFC5322ZoneResolver()
        assert resolver("est", None) == -5 * _HOUR
        assert resolver.unresolved is None

    def test_exported_names_match_the_table(self):
        assert RFC5322_ZONE_NAMES == tuple(sorted(n for n, _ in _RFC5322_TABLE))


class TestPassesResolvedOffsetsThrough:
    def test_numeric_offset_wins_over_the_table(self):
        """dateutil resolved it already (e.g. '+02:00', 'UTC') — keep it."""
        resolver = RFC5322ZoneResolver()
        assert resolver(None, 7200) == 7200
        assert resolver.unresolved is None

    def test_zero_offset_is_not_confused_with_absent(self):
        """UTC arrives as offset 0; a falsy-but-present offset must survive."""
        resolver = RFC5322ZoneResolver()
        assert resolver("UTC", 0) == 0
        assert resolver.unresolved is None

    def test_offset_wins_even_for_an_unknown_name(self):
        resolver = RFC5322ZoneResolver()
        assert resolver("XYZ", -3600) == -3600
        assert resolver.unresolved is None


class TestRefusesWhatItCannotResolve:
    def test_unknown_abbreviation_is_recorded(self):
        resolver = RFC5322ZoneResolver()
        assert resolver("XYZ", None) is None
        assert resolver.unresolved == "XYZ"

    def test_recorded_name_keeps_its_original_case(self):
        resolver = RFC5322ZoneResolver()
        assert resolver("xyz", None) is None
        assert resolver.unresolved == "xyz"

    @pytest.mark.parametrize("name", ["IST", "CET", "A", "Z ", "BST"])
    def test_zones_outside_rfc5322_are_refused(self, name):
        """RFC 5322 calls these unpredictable; guessing one is the defect."""
        resolver = RFC5322ZoneResolver()
        assert resolver(name, None) is None
        assert resolver.unresolved == name

    def test_no_zone_at_all_is_not_an_unresolved_zone(self):
        """A naive string calls back with (None, None); that is not a defect."""
        resolver = RFC5322ZoneResolver()
        assert resolver(None, None) is None
        assert resolver.unresolved is None

    def test_state_is_per_instance(self):
        first = RFC5322ZoneResolver()
        first("XYZ", None)
        second = RFC5322ZoneResolver()
        assert second.unresolved is None
