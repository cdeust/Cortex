"""Activation trust anchor: main's claude.yml CLAUDE_REVIEW_GATE (ADR-1116)."""

from __future__ import annotations

import base64
import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/ci_claude_review_gate.py"


def module():
    spec = importlib.util.spec_from_file_location("ci_claude_review_gate", SCRIPT)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def workflow(mode):
    text = f"name: Claude Code\nenv:\n  CLAUDE_REVIEW_GATE: {mode}\njobs: {{}}\n"
    return {
        "type": "file",
        "encoding": "base64",
        "content": base64.encodebytes(text.encode()).decode(),
    }


class GateTests(unittest.TestCase):
    def setUp(self):
        self.gate = module()

    def test_gate_line_decides_activation(self):
        mode = self.gate.declares_required
        self.assertTrue(mode("env:\n  CLAUDE_REVIEW_GATE: required\n"))
        self.assertFalse(mode("env:\n  CLAUDE_REVIEW_GATE: observe\n"))
        self.assertFalse(mode("name: Claude Code\n# CLAUDE_REVIEW_GATE: required\n"))
        self.assertTrue(mode("jobs:\n    CLAUDE_REVIEW_GATE: required\n"))
        # A variant the reader cannot classify fails loudly, never Codex-only.
        for text in (
            "env:\n  CLAUDE_REVIEW_GATE: required  # ADR-1116\n",
            "env:\n  CLAUDE_REVIEW_GATE: 'required'\n",
            "env:\n  CLAUDE_REVIEW_GATE:required\n",
            "env:\n  CLAUDE_REVIEW_GATE: maybe\n",
            "env:\n  CLAUDE_REVIEW_GATE: required\n  CLAUDE_REVIEW_GATE: observe\n",
        ):
            with self.subTest(text=text), self.assertRaises(self.gate.EvidenceError):
                mode(text)

    def test_main_workflow_listing_is_the_trust_anchor(self):
        calls = []

        def api(endpoint, **_):
            calls.append(endpoint)
            if endpoint.endswith("/contents/.github/workflows?ref=main"):
                return listing
            return content

        listing, content = [{"name": "pipeline.yml", "type": "file"}], None
        self.assertFalse(self.gate.main_requires_claude("cdeust/Cortex", api))
        self.assertEqual(
            calls, ["repos/cdeust/Cortex/contents/.github/workflows?ref=main"]
        )
        listing = [{"name": "claude.yml", "type": "file"}]
        for mode, expected in (("observe", False), ("required", True)):
            content = workflow(mode)
            self.assertIs(
                self.gate.main_requires_claude("cdeust/Cortex", api), expected
            )
        self.assertEqual(
            calls[-1],
            "repos/cdeust/Cortex/contents/.github/workflows/claude.yml?ref=main",
        )

    def test_unreadable_gate_blocks_instead_of_falling_back(self):
        def server(listing, content):
            def api(endpoint, **_):
                return content if "claude.yml" in endpoint else listing

            return api

        listing = [{"name": "claude.yml", "type": "file"}]
        for content in (
            {"encoding": "none", "content": ""},
            {"encoding": "base64", "content": "!!!"},
            {"encoding": "base64", "content": base64.b64encode(b"\xff").decode()},
            [],
        ):
            with (
                self.subTest(content=content),
                self.assertRaises(self.gate.EvidenceError),
            ):
                self.gate.main_requires_claude(
                    "cdeust/Cortex", server(listing, content)
                )
        for bad in ("x", [{"name": 1}], [{"name": "claude.yml", "type": "dir"}]):
            with (
                self.subTest(listing=bad),
                self.assertRaises(self.gate.EvidenceError),
            ):
                self.gate.main_requires_claude("cdeust/Cortex", server(bad, None))


if __name__ == "__main__":
    unittest.main()
