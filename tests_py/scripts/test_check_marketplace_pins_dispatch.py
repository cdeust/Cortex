"""Tests for scripts/check_marketplace_pins.py — `_check_plugin_pin` source-
shape dispatch. Split out of test_check_marketplace_pins.py (issue: that
file crossed the 300-line §4.1 cap once this coverage was added); same
`gate` module instance via _marketplace_pins_test_loader.py.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from tests_py.scripts._marketplace_pins_test_loader import gate


class TestPluginSourceDispatch(unittest.TestCase):
    """`_check_plugin_pin` — the schema defines 5 `source` shapes (verified
    live against json.schemastore.org/claude-code-marketplace.json), this
    gate implements checkers for 2 (github, local-path). The other 3
    (npm/url/git-subdir) must fail loudly, never pass through silently —
    a dispatcher returning ([], [], None) for a shape it does not recognize
    is exactly the defect class this gate exists to close, reproduced here
    against every schema-legal shape it does not check.
    """

    def _dispatch(self, source):
        return gate._check_plugin_pin("p", "1.0.0", source, Path("."))

    def test_npm_source_fails_loudly_not_silently(self):
        failures, notices, primary = self._dispatch(
            {"source": "npm", "package": "some-pkg", "version": "1.0.0"}
        )
        self.assertTrue(failures, "npm source must not silently pass")
        self.assertIn("UNVERIFIED_SOURCE_TYPE", failures[0])
        self.assertIn("npm", failures[0])
        self.assertIsNone(primary)

    def test_url_source_fails_loudly_not_silently(self):
        failures, _, _ = self._dispatch(
            {"source": "url", "url": "https://example.com/repo.git"}
        )
        self.assertTrue(failures, "url source must not silently pass")
        self.assertIn("UNVERIFIED_SOURCE_TYPE", failures[0])
        self.assertIn("url", failures[0])

    def test_git_subdir_source_fails_loudly_not_silently(self):
        failures, _, _ = self._dispatch(
            {"source": "git-subdir", "url": "owner/repo", "path": "sub"}
        )
        self.assertTrue(failures, "git-subdir source must not silently pass")
        self.assertIn("UNVERIFIED_SOURCE_TYPE", failures[0])
        self.assertIn("git-subdir", failures[0])

    def test_unknown_dict_shape_fails_loudly(self):
        failures, _, _ = self._dispatch({"source": "ftp"})
        self.assertTrue(failures)
        self.assertIn("UNRECOGNIZED_SOURCE", failures[0])

    def test_non_string_non_dict_source_fails_loudly(self):
        failures, _, _ = self._dispatch(42)
        self.assertTrue(failures)
        self.assertIn("UNRECOGNIZED_SOURCE", failures[0])

    def test_none_source_fails_loudly(self):
        failures, _, _ = self._dispatch(None)
        self.assertTrue(failures)
        self.assertIn("UNRECOGNIZED_SOURCE", failures[0])

    def test_github_source_still_dispatches_to_its_checker(self):
        # Regression guard for the refactor that split the github branch
        # into _check_github_source_pin: a github source must NOT fall
        # into the UNVERIFIED_SOURCE_TYPE/UNRECOGNIZED_SOURCE branches this
        # test class exists to cover. No live network call: check_github_pin
        # / check_pin_sha are stubbed at the module level for this test only.
        with (
            mock.patch.object(gate, "check_github_pin", return_value=(None, None)),
            mock.patch.object(gate, "check_pin_sha", return_value=(None, None)),
        ):
            failures, notices, primary = self._dispatch(
                {"source": "github", "repo": "o/r", "sha": "a" * 40}
            )
        self.assertEqual(failures, [])
        self.assertEqual(notices, [])
        self.assertIsNone(primary)


if __name__ == "__main__":
    unittest.main()
