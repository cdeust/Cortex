"""Tests for scripts/craftsmanship_baseline.py — the ratchet.

Pins the two failure directions the ratchet enforces against the baseline
committed in the same tree: a violation absent from that baseline is NEW
(blocks); a baseline entry whose violation no longer reproduces is STALE
(also blocks, forcing the baseline to be pruned rather than silently
drifting from reality). The end-to-end behaviour against real throwaway
git repos lives in ``test_check_craftsmanship_exploits.py``.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tests_py.scripts._craftsmanship_support import baseline_mod, rules

V1 = rules.Violation("a.py", "file-size", "exceeds 300-line cap")
V2 = rules.Violation("b.py", "method-size", "C.m")


class LoadSaveTests(unittest.TestCase):
    def test_load_missing_file_returns_empty_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(baseline_mod.load_baseline(Path(tmp) / "none.json"), set())

    def test_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "baseline.json"
            baseline_mod.save_baseline(path, {V1, V2})
            loaded = baseline_mod.load_baseline(path)
            self.assertEqual(loaded, {V1, V2})

    def test_saved_file_is_sorted_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "baseline.json"
            baseline_mod.save_baseline(path, {V2, V1})
            data = json.loads(path.read_text())
            files = [entry["file"] for entry in data["violations"]]
            self.assertEqual(files, sorted(files))


class DiffTests(unittest.TestCase):
    def test_new_violation_not_in_baseline(self) -> None:
        current = {V1, V2}
        result = baseline_mod.new_violations(current, {V1})
        self.assertEqual(result, [V2])

    def test_no_new_violations_when_subset_of_baseline(self) -> None:
        self.assertEqual(baseline_mod.new_violations({V1}, {V1, V2}), [])

    def test_stale_entry_when_violation_no_longer_reproduces(self) -> None:
        # V2 is baselined for b.py, but a fresh scan of b.py finds nothing.
        stale = baseline_mod.stale_entries({V1, V2}, {"a.py": {V1}, "b.py": set()})
        self.assertEqual(stale, [V2])

    def test_no_stale_entries_when_everything_still_reproduces(self) -> None:
        stale = baseline_mod.stale_entries({V1, V2}, {"a.py": {V1}, "b.py": {V2}})
        self.assertEqual(stale, [])

    def test_file_missing_from_rescan_map_is_stale(self) -> None:
        # A baselined file that no longer exists (deleted/renamed) rescans
        # to nothing — every entry for it is stale.
        stale = baseline_mod.stale_entries({V1}, {})
        self.assertEqual(stale, [V1])


class CountByKindTests(unittest.TestCase):
    def test_counts_grouped_and_sorted_by_kind(self) -> None:
        v3 = rules.Violation("c.py", "file-size", "exceeds 300-line cap")
        counts = baseline_mod.count_by_kind({V1, V2, v3})
        self.assertEqual(counts, {"file-size": 2, "method-size": 1})

    def test_empty_input_gives_empty_dict(self) -> None:
        self.assertEqual(baseline_mod.count_by_kind(set()), {})


class ParseBaselineJsonTests(unittest.TestCase):
    def test_parses_violations_array(self) -> None:
        text = json.dumps(
            {"violations": [{"file": "a.py", "kind": "file-size", "detail": "d"}]}
        )
        self.assertEqual(
            baseline_mod.parse_baseline_json(text),
            {rules.Violation("a.py", "file-size", "d")},
        )

    def test_missing_violations_key_gives_empty_set(self) -> None:
        self.assertEqual(baseline_mod.parse_baseline_json("{}"), set())


if __name__ == "__main__":
    unittest.main()
