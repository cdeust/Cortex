import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import sys

sys.path.insert(
    0,
    str(Path(__file__).resolve().parents[2] / "plugins/hypermnesia-mcp-codex/scripts"),
)
import cleanup_operations as h


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(
            prefix="hygiene-test-", dir=Path(__file__).parent
        )
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.repo = str(self.root / "main")
        self.remote = str(self.root / "remote.git")
        self.path = str(self.root / "tree\nwith space")
        h.run(["git", "init", "--bare", self.remote])
        h.run(["git", "init", "-b", "main", self.repo])
        h.git(self.repo, "config", "user.email", "test@example.invalid")
        h.git(self.repo, "config", "user.name", "Test")
        h.git(self.repo, "commit", "--allow-empty", "-m", "base")
        self.base = h.git(self.repo, "rev-parse", "HEAD")
        h.git(self.repo, "remote", "add", "origin", self.remote)
        h.git(self.repo, "push", "-u", "origin", "main")
        h.git(self.repo, "worktree", "add", "-b", "feature", self.path)
        h.git(self.path, "commit", "--allow-empty", "-m", "feature")
        h.git(self.path, "push", "-u", "origin", "feature")
        self.head = h.git(self.path, "rev-parse", "HEAD")
        h.git(self.remote, "update-ref", "refs/pull/1/head", self.head)
        self.state = {}
        self.owner = "codex:test"
        self.pr = "https://github.com/example/repo/pull/1"
        h.register_worktree(
            self.state, self.owner, self.path, {"repo": self.repo, "pr": self.pr}
        )
        self.evidence = self.root / "evidence.md"
        self.evidence.write_text("Durable test evidence")
        h.preserve(self.state, self.owner, self.path, str(self.evidence))
        self.real_run = h.run
        self.live = self.head
        self.calls = []
        self.patcher = patch.object(h, "run", side_effect=self.command)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def command(self, argv, cwd=None):
        self.calls.append(argv)
        if argv[0] == "gh":
            return json.dumps(
                {"url": self.pr, "headRefName": "feature", "headRefOid": self.live}
            )
        argv = [
            self.remote if arg == "https://github.com/example/repo.git" else arg
            for arg in argv
        ]
        return self.real_run(argv, cwd)

    def clean(self, **kwargs):
        return h.dispose(self.state, self.owner, self.path, kwargs)[0]

    def assert_protected(self):
        self.assertIn("protected", self.clean())
        self.assertTrue(Path(self.path).exists())

    def test_success_unmerged_branch_removed(self):
        self.assertIn("removed worktree and local branch", self.clean()["status"])
        self.assertFalse(Path(self.path).exists())
        self.assertEqual(h.git(self.repo, "branch", "--list", "feature"), "")
        self.assertEqual(h.git(self.repo, "for-each-ref", "refs/disk-hygiene"), "")

    def test_success_without_upstream(self):
        h.git(self.repo, "branch", "--unset-upstream", "feature")
        self.assertIn("and local branch", self.clean()["status"])

    def test_uncommitted_file(self):
        Path(self.path, "valuable").write_text("keep")
        self.assert_protected()

    def test_ignored_file(self):
        Path(self.path, ".gitignore").write_text("valuable\n")
        h.git(self.path, "add", ".gitignore")
        h.git(self.path, "commit", "-m", "ignore")
        Path(self.path, "valuable").write_text("keep")
        self.assert_protected()

    def test_local_unpushed(self):
        h.git(self.path, "commit", "--allow-empty", "-m", "unpushed")
        h.preserve(self.state, self.owner, self.path, str(self.evidence))
        self.assert_protected()

    def test_live_remote_rewritten_behind_stale_tracking(self):
        self.live = self.base
        h.git(self.remote, "update-ref", "refs/pull/1/head", self.base)
        self.assertEqual(h.git(self.repo, "rev-parse", "origin/feature"), self.head)
        self.assert_protected()

    def test_remote_changes_between_checks(self):
        with patch.object(h, "live_head", side_effect=[self.head, self.base]):
            self.assert_protected()

    def test_locked(self):
        h.git(self.repo, "worktree", "lock", self.path)
        self.assert_protected()

    def test_unknown_and_other_owner(self):
        result = h.dispose(self.state, "claude:other", self.path)
        self.assertIn("protected", result[0])
        self.state.clear()
        self.assert_protected()

    def test_main_cannot_register(self):
        with self.assertRaises(h.Protected):
            h.register_worktree(
                {}, self.owner, self.repo, {"repo": self.repo, "pr": self.pr}
            )

    def test_status_error(self):
        def fail(argv, cwd=None):
            if "status" in argv:
                raise h.Protected("status failed")
            return self.command(argv, cwd)

        with patch.object(h, "run", side_effect=fail):
            self.assert_protected()

    def test_remove_error_no_fallback(self):
        def fail(argv, cwd=None):
            if "remove" in argv:
                raise h.Protected("worktree remove refused")
            return self.command(argv, cwd)

        with patch.object(h, "run", side_effect=fail):
            self.assert_protected()

    def test_dry_run_does_not_fetch_or_remove(self):
        self.assertIn("would remove", self.clean(dry_run=True)["status"])
        self.assertTrue(Path(self.path).exists())
        self.assertFalse(any("fetch" in c or "remove" in c for c in self.calls))
        self.assertIn(self.path, self.state)

    def test_missing_or_changed_evidence(self):
        self.evidence.write_text("changed")
        self.assert_protected()

    def test_registration_before_pr(self):
        self.state[self.path]["pr"] = None
        self.assert_protected()

    def test_temp_only_explicit_owned_and_evidenced(self):
        path = str(self.root / "scratch")
        Path(path).mkdir()
        Path(path, "disposable").write_text("tmp")
        h.claim(self.state, path, self.owner, {"kind": "temp"})
        self.assertIn("protected", h.dispose(self.state, self.owner, path)[0])
        h.preserve(self.state, self.owner, path, str(self.evidence))
        self.assertIn("removed", h.dispose(self.state, self.owner, path)[0]["status"])
        self.assertFalse(Path(path).exists())

    def test_temp_with_git_checkout_retained(self):
        path = str(self.root / "scratch")
        Path(path, ".git").mkdir(parents=True)
        h.claim(self.state, path, self.owner, {"kind": "temp"})
        h.preserve(self.state, self.owner, path, str(self.evidence))
        self.assertIn("protected", h.dispose(self.state, self.owner, path)[0])

    def test_symlink_registration_refused(self):
        alias = self.root / "alias"
        alias.symlink_to(self.path)
        with self.assertRaises(h.Protected):
            h.claim({}, str(alias), self.owner, {"kind": "temp"})

    def test_active_file_prevents_removal(self):
        with open(Path(self.path, "open.tmp"), "w"):
            with self.assertRaises(h.Protected):
                h.no_open_files(self.path)

    def test_no_active_file_is_clear(self):
        h.no_open_files(self.path)
