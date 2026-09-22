"""File batch equivalence and an executed store-double/symlink counterexample."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mcp_server.core import wiki_sync
from mcp_server.handlers import codebase_analyze as codebase
from mcp_server.handlers import remember, remember_bulk
from tests_py.handlers._bulk_file_fakes import analysis, file_scenario
from tests_py.handlers._remember_bulk_fakes import harness


class FileBoundaries(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def files(self, names=("first.py", "second.py")):
        paths = [self.root / name for name in names]
        for index, path in enumerate(paths):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"Fixture file {index}: choose SQLite.")
        return paths

    def assert_same(self, before, after):
        self.assertEqual(before[0], after[0])
        self.assertEqual(before[1].store.rows, after[1].store.rows)
        self.assertEqual(before[1].store.events, after[1].store.events)
        self.assertEqual(before[1].store.read_versions, after[1].store.read_versions)
        self.assertEqual(before[1].telemetry.call_count, after[1].telemetry.call_count)

    def test_codebase_batch_preserves_metadata_entities_vectors_and_order(self):
        paths = self.files()
        old = file_scenario("codebase", paths, self.root, {"reference": True})
        new = file_scenario("codebase", paths, self.root)
        self.assert_same(old, new)
        self.assertEqual(len(new[1].engine.batches), 1)
        self.assertEqual(new[1].engine.scalars, [])
        self.assertEqual(new[0][:5], (2, 0, 0, 2, 4))

    def test_codebase_missing_and_unchanged_files_do_not_enter_batch(self):
        paths = self.files()
        existing = {
            paths[0].name: (
                1,
                analysis(paths[0].name, paths[0].read_text()).content_hash,
            )
        }
        paths.append(self.root / "missing.py")
        old = file_scenario(
            "codebase", paths, self.root, {"reference": True, "existing": existing}
        )
        new = file_scenario("codebase", paths, self.root, {"existing": existing})
        self.assert_same(old, new)
        self.assertEqual(len(new[1].engine.batches[0]), 1)

    def test_codebase_late_parse_error_keeps_prior_write(self):
        paths = self.files()

        def failure(env):
            def parse(relative, content):
                if relative == "second.py":
                    raise ValueError("late parse")
                return analysis(relative, content)

            env.stack.enter_context(patch.object(codebase, "_parse_one_file", parse))

        old = file_scenario(
            "codebase", paths, self.root, {"reference": True, "failure": failure}
        )
        new = file_scenario("codebase", paths, self.root, {"failure": failure})
        self.assert_same(old, new)
        self.assertEqual(len(new[1].store.rows), 1)

    def test_wiki_scalar_preserves_read_errors_and_imported_counter(self):
        paths = self.files(("README.md", "docs/second.md"))
        paths.insert(1, self.root / "docs/disappeared.md")
        old = file_scenario("wiki", paths, self.root, {"reference": True})
        new = file_scenario("wiki", paths, self.root)
        self.assert_same(old, new)
        self.assertEqual(new[0]["imported"], 2)
        self.assertEqual(new[0]["error_count"], 1)
        self.assertEqual(new[1].engine.batches, [])
        self.assertEqual(new[1].engine.scalars, old[1].engine.scalars)

    def test_resolved_symlink_to_writer_tree_prevents_preparing_live_reads(self):
        root = self.root / "writer"
        root.mkdir()
        target = root / "page.md"
        target.write_text("page")
        link = self.root / "source.py"
        link.symlink_to(target)
        with harness() as env:
            env.stack.enter_context(patch.object(remember, "WIKI_ROOT", root))
            self.assertFalse(remember_bulk.file_reads_are_independent([link]))
            self.assertTrue(
                remember_bulk.file_reads_are_independent([self.root / "other.py"])
            )

    def test_hardlink_alias_keeps_live_reads_sequential(self):
        target = self.root / "state.db"
        target.write_text("fixture state")
        alias = self.root / "alias.py"
        alias.hardlink_to(target)
        with harness():
            self.assertFalse(remember_bulk.file_reads_are_independent([alias]))

    def test_store_file_write_changes_later_codebase_symlink_read(self):
        self._live_read_counterexample("codebase")

    def test_store_file_write_changes_later_wiki_seed_read(self):
        self._live_read_counterexample("wiki")

    def test_current_bulk_tags_prevent_wiki_publication_before_user_rules(self):
        content = "Decision: SQLite owns the memory store. " * 3
        for audit_tag in ("seeded", "codebase", "imported"):
            self.assertIsNone(
                wiki_sync.build_from_memory(
                    memory_id=1,
                    content=content,
                    tags=[audit_tag, "adr"],
                    memory_source="",
                    domain="fixture",
                )
            )

    def _live_read_counterexample(self, mode):
        first = self.files(("first.py",) if mode == "codebase" else ("README.md",))[0]
        target = self.root / "state/memory.db"
        target.parent.mkdir(parents=True, exist_ok=True)
        second = self.root / ("second.py" if mode == "codebase" else "docs/state.md")
        second.parent.mkdir(parents=True, exist_ok=True)
        second.symlink_to(target)
        observations = []
        variants = [{"reference": True}, {}]
        if mode == "codebase":
            variants.append({"force_batch": True})
        for options in variants:
            target.write_text("stale contents before the first remember")
            observations.append(
                file_scenario(
                    mode, [first, second], self.root, {"state_file": target, **options}
                )
            )
        self.assert_same(observations[0], observations[1])
        self.assertEqual(observations[1][1].engine.batches, [])
        live_text = observations[1][1].store.rows[1][0]
        self.assertIn("persisted row 1", live_text)
        if mode == "codebase":
            frozen_text = observations[2][1].store.rows[1][0]
            self.assertIn("stale contents", frozen_text)
            self.assertNotEqual(live_text, frozen_text)


if __name__ == "__main__":
    unittest.main()
