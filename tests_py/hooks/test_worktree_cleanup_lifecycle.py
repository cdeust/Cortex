"""Real Git acceptance for shared host recovery, based on ADR-1092 ."""

import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
import test_worktree_cleanup as base
import cleanup_hooks as hooks
import cleanup_intake
import disk_hygiene
import cleanup_operations as h
from cleanup_registry import Protected, registry


class LifecycleTests(base.CleanupTests):
    def hook(self, event, owner="codex:new"):
        host, session = owner.split(":")
        args = SimpleNamespace(event=event, host=host, session=session)
        return hooks.hook_result(self.state, owner, args, {"cwd": self.repo})

    def test_cross_host_recovery_keeps_transcripts(self):
        transcript = self.root / "transcript.jsonl"
        transcript.write_bytes(b'{"text":"resume this"}\n')
        before = transcript.read_bytes()
        self.hook("SessionEnd", self.owner)
        self.hook("SessionStart", "claude:new")
        self.assertFalse(Path(self.path).exists())
        self.assertEqual(transcript.read_bytes(), before)
        self.assertEqual(h.git(self.repo, "branch", "--list", "feature"), "")

    def test_active_other_owner_is_not_swept(self):
        self.hook("SessionStart", "claude:new")
        self.assertTrue(Path(self.path).exists())

    def test_resume_cancels_ended(self):
        self.hook("SessionEnd", self.owner)
        self.hook("SessionStart", self.owner)
        self.assertTrue(Path(self.path).exists())
        self.assertNotIn(self.owner, self.state["_ended"])

    def test_end_is_durable_without_subprocess(self):
        ledger = self.root / "registry.json"
        with patch.object(
            h.subprocess, "run", side_effect=AssertionError("no subprocess on end")
        ):
            with registry(ledger) as state:
                hooks.hook_result(
                    state, self.owner, SimpleNamespace(event="SessionEnd"), {}
                )
        self.assertTrue(json.loads(ledger.read_text())["_ended"][self.owner])

    def test_pending_branch_retry_survives_ledger_reload(self):
        def fail(argv, cwd=None):
            if "branch" in argv and "-d" in argv:
                raise Protected("injected branch rejection")
            return self.command(argv, cwd)

        with patch.object(h, "run", side_effect=fail):
            self.assertIn("protected", self.clean())
        self.assertFalse(Path(self.path).exists())
        self.assertTrue(self.state[self.path]["pending_branch"])
        self.state = json.loads(json.dumps(self.state))
        self.assertIn("local branch", self.clean()["status"])
        self.assertNotIn(self.path, self.state)

    def test_pending_branch_advanced_is_protected(self):
        def fail(argv, cwd=None):
            if "branch" in argv and "-d" in argv:
                raise Protected("injected branch rejection")
            return self.command(argv, cwd)

        with patch.object(h, "run", side_effect=fail):
            self.clean()
        h.git(self.repo, "update-ref", "refs/heads/feature", self.base)
        self.assertIn("protected", self.clean())
        self.assertIn(self.path, self.state)

    def test_other_repository_ended_owner_retained(self):
        self.hook("SessionEnd", self.owner)
        with patch.object(hooks, "scope", return_value="/another/repo"):
            self.hook("SessionStart", "claude:new")
        self.assertTrue(Path(self.path).exists())

    def test_unavailable_lsof_fails_closed(self):
        with patch.object(h.subprocess, "run", side_effect=FileNotFoundError("lsof")):
            with self.assertRaises(Protected):
                h.no_open_files(self.path)

    def test_malformed_ledger_is_not_replaced(self):
        ledger = self.root / "registry.json"
        for text in ("[]", '{"/path": null}', '{"_ended": {"x": 0}}', "invalid"):
            ledger.write_text(text)
            with self.assertRaises((Protected, ValueError)), registry(ledger):
                pass
            self.assertEqual(ledger.read_text(), text)

    def test_start_outside_git_with_no_ended_records(self):
        args = SimpleNamespace(event="SessionStart", host="codex", session="fresh")
        with patch.object(hooks, "scope", side_effect=AssertionError("not needed")):
            result = hooks.hook_result({}, "codex:fresh", args, {"cwd": str(self.root)})
        self.assertIn("hookSpecificOutput", result)

    def test_start_outside_git_retains_ended_records(self):
        self.hook("SessionEnd", self.owner)
        args = SimpleNamespace(event="SessionStart", host="codex", session="fresh")
        with patch.dict(os.environ, {"GIT_CEILING_DIRECTORIES": str(self.root.parent)}):
            result = hooks.hook_result(
                self.state, "codex:fresh", args, {"cwd": str(self.root)}
            )
        self.assertIn("protected", result["hookSpecificOutput"]["additionalContext"])
        self.assertTrue(Path(self.path).exists())

    def test_created_temp_has_scope_and_is_recovered(self):
        with patch.object(h.Path, "cwd", return_value=Path(self.repo)):
            path = h.create_temp(self.state, self.owner, str(self.root))["created"]
        self.assertEqual(self.state[path]["repo"], self.repo)
        h.preserve(self.state, self.owner, path, str(self.evidence))
        self.hook("SessionEnd", self.owner)
        self.hook("SessionStart", "claude:new")
        self.assertFalse(Path(path).exists())

    def test_intake_startup_recovers_real_git_worktree_across_hosts(self):
        ledger = self.root / "ownership.json"
        with registry(ledger) as state:
            state.update(self.state)
        end_args = SimpleNamespace(state=str(ledger), host="codex", session="test")
        cleanup_intake.record_end(end_args, {"cwd": self.repo})
        start_args = SimpleNamespace(
            state=str(ledger),
            host="claude",
            session="new",
            command="hook",
            event="SessionStart",
        )
        with patch.object(
            disk_hygiene.host_cleanup, "after_hook", side_effect=lambda a, p, r: r
        ):
            disk_hygiene.run_command(start_args, {"cwd": self.repo})
        self.assertFalse(Path(self.path).exists())
        self.assertEqual(h.git(self.repo, "branch", "--list", "feature"), "")
        self.assertEqual(cleanup_intake.read_pending(ledger, "worktree"), [])
        self.assertEqual(len(cleanup_intake.read_pending(ledger, "host")), 1)
