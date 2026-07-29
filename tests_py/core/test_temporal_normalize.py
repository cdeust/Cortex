"""Tests for mcp_server.core.temporal_normalize — storage normalization.

Issue #252: a stated timezone is honoured or the value is refused, never
dropped — a dropped zone reads as UTC in PostgreSQL's `timestamptz` cast and
in `temporal.compute_recency_boost`, so dropping it persists a wrong instant.
"""

import ast
import inspect
import logging
import sys
import warnings
from datetime import datetime, timezone

from mcp_server.core import temporal_normalize, temporal_timezones
from mcp_server.core.temporal_normalize import normalize_date_to_iso


class TestNormalizeDateToIso:
    """Storage normalization — issue #252: a stated zone is honoured or
    refused, never dropped (a dropped zone reads as UTC downstream)."""

    def test_empty(self):
        assert normalize_date_to_iso("") is None
        assert normalize_date_to_iso("   ") is None

    def test_iso_datetime_passes_through_verbatim(self):
        raw = "2023-05-08T13:56:00+02:00"
        assert normalize_date_to_iso(raw) == raw

    def test_iso_datetime_without_seconds_keeps_its_time(self):
        assert normalize_date_to_iso("2023-05-08T13:56") == "2023-05-08T13:56"

    def test_date_only_fast_path(self):
        assert normalize_date_to_iso("8 May 2023") == "2023-05-08T00:00:00"
        assert normalize_date_to_iso("May 8, 2023") == "2023-05-08T00:00:00"

    def test_date_only_string_the_fast_path_misses(self):
        """No time of day, no fast-path match — dateutil still resolves it."""
        assert normalize_date_to_iso("8th of May 2023") == "2023-05-08T00:00:00"

    def test_locomo_format_keeps_its_time_and_stays_naive(self):
        """No zone stated → no zone invented."""
        assert normalize_date_to_iso("1:56 pm on 8 May, 2023") == (
            "2023-05-08T13:56:00"
        )

    def test_numeric_offset_is_preserved(self):
        assert normalize_date_to_iso("8 May 2023 13:56 +02:00") == (
            "2023-05-08T13:56:00+02:00"
        )

    def test_utc_is_preserved(self):
        assert normalize_date_to_iso("8 May 2023 13:56 UTC") == (
            "2023-05-08T13:56:00+00:00"
        )

    def test_unparseable(self):
        assert normalize_date_to_iso("not a date") is None
        assert normalize_date_to_iso("2023/04/10 (Mon) 17:50") is None


class TestNormalizeDateToIsoTimezoneAbbreviations:
    """Issue #252 regression: these all returned a wrong instant before."""

    def test_est_resolves_to_the_rfc5322_offset(self):
        assert normalize_date_to_iso("8 May 2023 13:56 EST") == (
            "2023-05-08T13:56:00-05:00"
        )

    def test_est_denotes_the_right_instant(self):
        """The value stored must be 18:56Z, not 13:56Z (the silent UTC re-anchor)."""
        stored = normalize_date_to_iso("8 May 2023 13:56 EST")
        assert stored is not None
        instant = datetime.fromisoformat(stored).astimezone(timezone.utc)
        assert instant == datetime(2023, 5, 8, 18, 56, tzinfo=timezone.utc)

    def test_rfc2822_style_with_abbreviation(self):
        assert normalize_date_to_iso("Mon, 8 May 2023 13:56:00 EST") == (
            "2023-05-08T13:56:00-05:00"
        )

    def test_abbreviation_containing_t_is_not_mistaken_for_iso(self):
        """'PST'/'EST'/'CST'/'MST' all contain a 'T': the old substring guard
        returned strings like this one unparsed."""
        assert normalize_date_to_iso("8 May 2023 13:56 PST") == (
            "2023-05-08T13:56:00-08:00"
        )

    def test_time_is_not_dropped_for_a_zone_bearing_string(self):
        assert normalize_date_to_iso("May 8, 2023 13:56 CST") == (
            "2023-05-08T13:56:00-06:00"
        )

    def test_unresolvable_abbreviation_is_refused(self, caplog):
        with caplog.at_level(
            logging.WARNING, logger="mcp_server.core.temporal_normalize"
        ):
            assert normalize_date_to_iso("8 May 2023 13:56 XYZ") is None
        assert len(caplog.records) == 1
        assert caplog.records[0].levelno == logging.WARNING

    def test_refusal_signal_is_actionable_verbatim(self, caplog):
        """The signal names the input, the abbreviation, the resolvable set,
        the consequence avoided and the fix. Asserted whole: every fragment
        of an operator-facing message is part of its contract."""
        with caplog.at_level(
            logging.WARNING, logger="mcp_server.core.temporal_normalize"
        ):
            normalize_date_to_iso("8 May 2023 13:56 IST")
        assert caplog.records[0].getMessage() == (
            "Refusing date '8 May 2023 13:56 IST': timezone abbreviation 'IST' "
            "is not resolvable (RFC 5322 §4.3 defines only CDT, CST, EDT, EST, "
            "GMT, MDT, MST, PDT, PST, UT), and re-anchoring it to UTC would "
            "store the wrong instant. Emit a numeric UTC offset (e.g. -05:00) "
            "instead; this value was NOT normalized."
        )

    def test_resolvable_abbreviation_is_quiet(self, caplog):
        with caplog.at_level(
            logging.WARNING, logger="mcp_server.core.temporal_normalize"
        ):
            normalize_date_to_iso("8 May 2023 13:56 EST")
        assert caplog.records == []

    def test_parse_emits_no_python_warning(self):
        """Criterion 3: the fix must not depend on warnings state. dateutil's
        UnknownTimezoneWarning is never raised once a tzinfos policy is
        supplied, so no filter has to be touched on the write path."""
        with warnings.catch_warnings(record=True) as raised:
            warnings.simplefilter("always")
            normalize_date_to_iso("8 May 2023 13:56 XYZ")
        assert raised == []

    def test_no_warnings_filter_mutation_on_the_write_path(self):
        """Criterion 3, pinned at the source: `warnings.catch_warnings()` is
        process-global and not thread-safe; it must not appear on this path.

        Asserted over the AST, not the text, so the modules stay free to
        EXPLAIN in prose why they do not do this."""
        banned_calls = {"catch_warnings", "simplefilter", "filterwarnings"}
        for module in (temporal_normalize, temporal_timezones):
            tree = ast.parse(inspect.getsource(module))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    assert all(a.name != "warnings" for a in node.names)
                elif isinstance(node, ast.ImportFrom):
                    assert node.module != "warnings"
                elif isinstance(node, ast.Attribute):
                    assert node.attr not in banned_calls
                elif isinstance(node, ast.Name):
                    assert node.id not in banned_calls


class TestNormalizeDateToIsoDegradedModes:
    def test_unparseable_time_of_day_salvages_the_date_and_says_so(self, caplog):
        with caplog.at_level(
            logging.WARNING, logger="mcp_server.core.temporal_normalize"
        ):
            assert normalize_date_to_iso("8 May 2023 25:99") == "2023-05-08T00:00:00"
        assert caplog.records[0].getMessage() == (
            "Date '8 May 2023 25:99' states a time of day that is not "
            "parseable; storing the date alone (2023-05-08), so its time "
            "is lost."
        )

    def test_fast_path_date_is_stored_without_a_degradation_signal(self, caplog):
        """A date-only string the built-in parsers handle must not be routed
        through the salvage path, which would report a loss that never
        happened."""
        with caplog.at_level(
            logging.WARNING, logger="mcp_server.core.temporal_normalize"
        ):
            assert normalize_date_to_iso("Created on 2024-06-01 at noon") == (
                "2024-06-01T00:00:00"
            )
        assert caplog.records == []

    def test_nothing_salvageable_returns_none_quietly(self, caplog):
        with caplog.at_level(
            logging.WARNING, logger="mcp_server.core.temporal_normalize"
        ):
            assert normalize_date_to_iso("half past forever") is None
        assert caplog.records == []

    def test_parser_overflow_is_not_propagated(self, monkeypatch, caplog):
        def _raise(*_args, **_kwargs):
            raise OverflowError("date value out of range")

        monkeypatch.setattr("dateutil.parser.parse", _raise)
        with caplog.at_level(
            logging.WARNING, logger="mcp_server.core.temporal_normalize"
        ):
            assert normalize_date_to_iso("8 May 2023 13:56") == "2023-05-08T00:00:00"
        assert "its time is lost" in caplog.text

    def test_missing_dateutil_is_reported_not_swallowed(self, monkeypatch, caplog):
        monkeypatch.setitem(sys.modules, "dateutil", None)
        with caplog.at_level(
            logging.WARNING, logger="mcp_server.core.temporal_normalize"
        ):
            assert normalize_date_to_iso("1:56 pm on 8 May, 2023") is None
        assert caplog.records[0].getMessage() == (
            "Cannot normalize date '1:56 pm on 8 May, 2023': python-dateutil "
            "is not installed, so only date-only formats are parseable. "
            "Install python-dateutil to store the time of day and timezone of "
            "free-form dates."
        )

    def test_missing_dateutil_still_salvages_a_date(self, monkeypatch, caplog):
        monkeypatch.setitem(sys.modules, "dateutil", None)
        with caplog.at_level(
            logging.WARNING, logger="mcp_server.core.temporal_normalize"
        ):
            assert normalize_date_to_iso("8 May 2023 13:56") == "2023-05-08T00:00:00"
        assert "python-dateutil is not installed" in caplog.text


class TestNormalizeDateToIsoWithoutDateutil:
    """The contract when the parser is absent (a `--no-deps` install).

    `python-dateutil` is a declared dependency, so every supported install
    has it — but the import is still a probe, and the guarantee of issue #252
    must hold on the degraded path too: a stated timezone is honoured or the
    value is refused. Salvaging the date alone would store a naive timestamp,
    which is the very thing every consumer reads back as UTC.
    """

    @staticmethod
    def _without_dateutil(monkeypatch):
        monkeypatch.setitem(sys.modules, "dateutil", None)

    def test_zone_bearing_date_is_refused_not_flattened(self, monkeypatch, caplog):
        self._without_dateutil(monkeypatch)
        with caplog.at_level(
            logging.WARNING, logger="mcp_server.core.temporal_normalize"
        ):
            assert normalize_date_to_iso("8 May 2023 13:56 EST") is None
        assert caplog.records[-1].getMessage() == (
            "Refusing date '8 May 2023 13:56 EST': it states a timezone, and "
            "the parse that would apply it did not produce a value. Salvaging "
            "the date alone would store a naive timestamp, which every "
            "consumer reads as UTC; this value was NOT normalized."
        )

    def test_numeric_offset_is_refused_too(self, monkeypatch):
        self._without_dateutil(monkeypatch)
        assert normalize_date_to_iso("8 May 2023 13:56 +02:00") is None

    def test_date_only_input_is_unaffected(self, monkeypatch, caplog):
        self._without_dateutil(monkeypatch)
        with caplog.at_level(
            logging.WARNING, logger="mcp_server.core.temporal_normalize"
        ):
            assert normalize_date_to_iso("8 May 2023") == "2023-05-08T00:00:00"
        assert caplog.records == []

    def test_zoneless_string_still_salvages_its_date(self, monkeypatch):
        self._without_dateutil(monkeypatch)
        assert normalize_date_to_iso("8 May 2023 13:56") == "2023-05-08T00:00:00"


class TestStatedZoneDetection:
    """`_STATED_ZONE_RE` decides refuse-vs-salvage, so its boundaries are
    part of the contract, not an implementation detail."""

    def test_zone_bearing_strings_are_detected(self):
        for raw in (
            "8 May 2023 13:56 EST",
            "Mon, 8 May 2023 13:56:00 EST",
            "8 May 2023 13:56 +02:00",
            "8 May 2023 13:56 -0500",
            "8 May 2023 13:56 UTC",
        ):
            assert temporal_normalize._STATED_ZONE_RE.search(raw), raw

    def test_zoneless_strings_are_not(self):
        for raw in (
            "8 May 2023",
            "1:56 pm on 8 May, 2023",
            "8 May 2023 25:99",
            "2023/04/10 (Mon) 17:50",
            "Created on 2024-06-01 at noon",
        ):
            assert not temporal_normalize._STATED_ZONE_RE.search(raw), raw
