"""The registered-equivalents gate must fail closed (§12.4).

This gate exists to let a survivor be accepted with a written rationale. That
is exactly the shape of a suppression mechanism, and a suppression mechanism
that can be wrong quietly is worse than no gate at all — the same script
already produced one false green (it reported `0 surviving mutants` on a run
whose own counter said 423).

So the tests here are mostly about what the registry must *refuse*: an entry
whose recorded mutation no longer matches, an entry matching nothing, a
rationale that says nothing, an unknown kind. The happy path is one test; the
refusals are the point.
"""

from __future__ import annotations

import json

import pytest

from scripts.mutation_equivalents import (
    Equivalent,
    RegistryError,
    classify,
    format_report,
    parse_registry,
    parse_survivors,
)

_PATHS = frozenset({"mcp_server/core/ast_extractors.py"})


def _entry(**over) -> dict:
    base = {
        "mutant": "mcp_server.core.ast_extractors.x__walk_type__mutmut_1",
        "removed": 'base = text.rsplit(".", 1)[-1]',
        "added": 'base = text.rsplit(".", 2)[-1]',
        "kind": "equivalent-by-construction",
        "rationale": (
            "rsplit(sep, n)[-1] selects the last element for every n, "
            "so maxsplit cannot matter."
        ),
        "issue": "#369",
    }
    base.update(over)
    return base


def _registry(*entries: dict) -> str:
    return json.dumps({"schema_version": 1, "equivalents": list(entries)})


class TestRegistryValidation:
    def test_a_well_formed_entry_loads(self) -> None:
        (e,) = parse_registry(_registry(_entry()))
        assert e.kind == "equivalent-by-construction"
        assert e.source_path == "mcp_server/core/ast_extractors.py"

    @pytest.mark.parametrize(
        "field", ["mutant", "removed", "added", "kind", "rationale", "issue"]
    )
    def test_every_field_is_mandatory(self, field: str) -> None:
        with pytest.raises(RegistryError, match=field):
            parse_registry(_registry(_entry(**{field: ""})))

    def test_an_unknown_kind_is_refused(self) -> None:
        """The kind vocabulary is closed on purpose: 'equivalent-by-construction'
        can never become false, 'unreachable-branch' can. A free-text kind would
        let those two blur.
        """
        with pytest.raises(RegistryError, match="unknown kind"):
            parse_registry(_registry(_entry(kind="probably-fine")))

    def test_a_token_rationale_is_refused(self) -> None:
        """'equivalent' as a bare word is the thing this gate exists to stop
        anyone writing.
        """
        with pytest.raises(RegistryError, match="rationale"):
            parse_registry(_registry(_entry(rationale="equivalent")))

    def test_a_duplicate_mutant_is_refused(self) -> None:
        with pytest.raises(RegistryError, match="duplicate"):
            parse_registry(_registry(_entry(), _entry()))

    def test_malformed_json_is_refused_rather_than_ignored(self) -> None:
        with pytest.raises(RegistryError, match="not valid JSON"):
            parse_registry("{not json")

    def test_a_missing_equivalents_key_is_refused(self) -> None:
        with pytest.raises(RegistryError, match="must be a list"):
            parse_registry(json.dumps({"schema_version": 1}))


class TestClassification:
    NAME = "mcp_server.core.ast_extractors.x__walk_type__mutmut_1"

    def _reg(self, **over) -> list[Equivalent]:
        return parse_registry(_registry(_entry(**over)))

    def test_a_matching_survivor_is_accepted(self) -> None:
        reg = self._reg()
        v = classify(
            [self.NAME], reg, {self.NAME: (reg[0].removed, reg[0].added)}, _PATHS
        )
        assert v.ok
        assert [n for n, _ in v.accepted] == [self.NAME]

    def test_a_survivor_absent_from_the_registry_is_unregistered(self) -> None:
        other = "mcp_server.core.ast_extractors.x__other__mutmut_9"
        v = classify([other], self._reg(), {other: ("a", "b")}, _PATHS)
        assert not v.ok
        assert v.unregistered == [other]

    def test_a_drifted_mutation_is_not_absolved(self) -> None:
        """The load-bearing property. mutmut numbers mutants positionally, so
        after the code moves the same name is a DIFFERENT mutation. Matching on
        the name alone would silently absolve whatever now occupies the slot.
        """
        reg = self._reg()
        drifted = {self.NAME: ("something = else()", "something = other()")}
        v = classify([self.NAME], reg, drifted, _PATHS)
        assert not v.ok
        assert [n for n, _ in v.mismatched] == [self.NAME]
        assert not v.accepted

    def test_an_entry_matching_no_survivor_is_stale(self) -> None:
        """Either a test now kills it, so the entry is dead weight, or the code
        moved, so the rationale is unverified. Both need a human.
        """
        v = classify([], self._reg(), {}, _PATHS)
        assert not v.ok
        assert [e.mutant for e in v.stale] == [self.NAME]

    def test_an_entry_for_a_file_this_run_did_not_mutate_is_not_stale(self) -> None:
        """A scoped run mutates a few files; entries for the others are out of
        scope, not rotten. Without this the gate would be unusable for scoped
        runs, which is the tier it is meant to serve.
        """
        v = classify([], self._reg(), {}, frozenset({"mcp_server/core/other.py"}))
        assert v.ok
        assert not v.stale


class TestSurvivorParsing:
    def test_only_survived_rows_are_taken(self) -> None:
        text = (
            "    a.b.x__f__mutmut_1: survived\n"
            "    a.b.x__f__mutmut_2: killed\n"
            "    a.b.x__f__mutmut_3: no tests\n"
            "    a.b.x__f__mutmut_4: survived\n"
        )
        assert parse_survivors(text) == ["a.b.x__f__mutmut_1", "a.b.x__f__mutmut_4"]

    def test_duplicates_are_collapsed(self) -> None:
        text = "  a.b.x__f__mutmut_1: survived\n  a.b.x__f__mutmut_1: survived\n"
        assert parse_survivors(text) == ["a.b.x__f__mutmut_1"]

    def test_empty_input_yields_nothing(self) -> None:
        assert parse_survivors("") == []


class TestReport:
    def test_a_clean_run_says_so(self) -> None:
        v = classify([], [], {}, _PATHS)
        assert "0 surviving mutants" in format_report(v)

    def test_drift_is_reported_with_the_recorded_diff(self) -> None:
        reg = parse_registry(_registry(_entry()))
        name = reg[0].mutant
        v = classify([name], reg, {name: ("x", "y")}, _PATHS)
        out = format_report(v)
        assert "NO LONGER MATCH" in out
        assert reg[0].removed in out, "the reader needs to see what was registered"


class TestCommittedRegistry:
    def test_the_repositorys_own_registry_is_valid(self) -> None:
        """A malformed registry disables the exemption path, and the gate would
        then fail on justified survivors — noisy, but also a signal nobody
        reads. Validate it in CI rather than on first use.
        """
        from scripts.mutation_equivalents import load_registry

        entries = load_registry()
        assert entries, "registry should carry the documented equivalents"
        for e in entries:
            assert e.issue.startswith("#"), (
                f"{e.mutant}: issue must reference a filed number"
            )
