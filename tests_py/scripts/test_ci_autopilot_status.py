"""The dispatcher updates one public comment without blocking actual repair."""

import io
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from ci_autopilot_status import MARKER, publish  # noqa: E402


class StatusTests(unittest.TestCase):
    def test_existing_maintainer_comment_is_updated_and_phase_is_not_repeated(self):
        options = SimpleNamespace(repository="cdeust/Cortex", status_comments=True)
        item = {"kind": "pull", "number": 776}
        existing = {"id": 10, "user": {"login": "cdeust"}, "body": "old\n" + MARKER}
        github = Mock(
            side_effect=[
                {"login": "cdeust"},
                [[existing]],
                {"headRefOid": "a" * 40},
                {},
            ]
        )
        publish(options, github, item, "dispatched")
        self.assertIn("PATCH", github.call_args.args)
        self.assertIn("repos/cdeust/Cortex/issues/comments/10", github.call_args.args)
        count = github.call_count
        publish(options, github, item, "dispatched")
        self.assertEqual(github.call_count, count)

    def test_comment_permission_failure_does_not_block_worker_handling(self):
        options = SimpleNamespace(repository="cdeust/Cortex", status_comments=True)
        item = {"kind": "pull", "number": 776}
        github = Mock(side_effect=subprocess.CalledProcessError(1, ["gh", "api"]))
        with patch.object(sys, "stderr", new=io.StringIO()) as error:
            publish(options, github, item, "failed")
        self.assertIn("status comment failed", error.getvalue())
        self.assertNotIn("announced_phase", item)

    def test_status_publication_requires_explicit_enablement(self):
        github = Mock()
        publish(SimpleNamespace(status_comments=False), github, {}, "dispatched")
        github.assert_not_called()

    def test_deleted_comment_author_does_not_block_status_publication(self):
        options = SimpleNamespace(repository="cdeust/Cortex", status_comments=True)
        item = {"kind": "pull", "number": 776}
        github = Mock(
            side_effect=[
                {"login": "cdeust"},
                [[{"user": None, "body": None}]],
                {"headRefOid": "a" * 40},
                {},
            ]
        )
        publish(options, github, item, "dispatched")
        self.assertIn("POST", github.call_args.args)
        self.assertEqual(item["announced_phase"], "dispatched")
