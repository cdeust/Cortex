"""Contract tests for the prose that describes the Codex plugin.

The package's own README and SECURITY.md, and the repository docs that
describe it, kept claiming the reduced design after the manifests stopped
implementing it (PR #620 review). These guards read the manifests and fail
when the prose disagrees with them.

Split from test_codex_plugin_contract.py, which asserts the manifests
themselves, to keep both files under the 300-line cap.
"""

from __future__ import annotations

import re

from tests_py.scripts._codex_plugin_support import (
    MCP_PATH,
    PLUGIN_PATH,
    PLUGIN_ROOT,
    REPO_ROOT,
    read_json as _json,
)

# Prose describing this package, in the files a user or a registry reviewer
# actually reads. scripts/check_doc_claims.py cannot cover these: every one of
# its patterns matches a NUMBER next to a keyword ("57 MCP tools", "97-reference"),
# and a design claim like "installs no hooks" carries no number to compare.
CODEX_PROSE_PATHS = (
    PLUGIN_ROOT / "README.md",
    PLUGIN_ROOT / "SECURITY.md",
    REPO_ROOT / "README.md",
    REPO_ROOT / "docs/codex-plugin.md",
    REPO_ROOT / "docs/shared-host-memory.md",
)

# Phrasings the shipped manifests contradict. Each is the literal wording that
# drifted (PR #620 review), not a ban on the words themselves: the docs still
# have to explain `--profile lean` as an opt-in, and that must keep passing.
NO_HOOKS_CLAIM = re.compile(r"installs no (?:lifecycle )?hooks", re.IGNORECASE)
# `tools?\b`, not `tool\b`: the trailing boundary never matched the plural,
# because the `s` in "tools" is itself a word character. That let the exact
# line this guard exists to catch, "the lean profile is exactly these ten
# tools:", pass. Every form below is covered by the test beneath it.
LEAN_SURFACE_CLAIM = re.compile(r"\b(?:10|ten)[- ]tools?\b", re.IGNORECASE)


def test_codex_prose_does_not_contradict_the_shipped_manifests() -> None:
    """The shipped docs described the old reduced design after the manifests
    stopped implementing it: a `lean` surface and "installs no hooks" in the
    package's own SECURITY.md, which is what a registry reviewer reads.

    The check is conditioned on the manifests, so reverting the design
    relaxes the guard instead of stranding it.
    """
    declares_hooks = "hooks" in _json(PLUGIN_PATH)
    serves_full = "--profile" not in _json(MCP_PATH)["mcpServers"]["cortex"]["args"]

    for path in CODEX_PROSE_PATHS:
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(REPO_ROOT)
        if declares_hooks:
            assert not NO_HOOKS_CLAIM.search(text), (
                f"{relative} says the package installs no hooks, but "
                f"{PLUGIN_PATH.relative_to(REPO_ROOT)} declares a hooks manifest"
            )
        if serves_full:
            assert not LEAN_SURFACE_CLAIM.search(text), (
                f"{relative} describes a ten-tool surface, but "
                f"{MCP_PATH.relative_to(REPO_ROOT)} passes no --profile flag, "
                "so the server serves the full profile"
            )


def test_the_drift_patterns_match_the_wordings_they_exist_to_catch() -> None:
    """A guard nobody tests is a guard that silently matches nothing.

    `\\b` after "tool" looked right and excluded every plural, so the
    historical phrasing this pattern was written for went on passing.
    """
    for wording in (
        "The lean profile is exactly these ten tools:",  # the historical line
        "a 10-tool lean surface",
        "its ten-tool `lean` profile",
        "10 tools",
        "ten tools",
    ):
        assert LEAN_SURFACE_CLAIM.search(wording), wording

    for wording in (
        "It installs no hooks, skills, apps or agents",
        "the package installs no lifecycle hooks",
    ):
        assert NO_HOOKS_CLAIM.search(wording), wording

    # The prose this package actually ships must not trip either pattern, or
    # the guard is a tripwire on its own documentation.
    for benign in (
        "the `lean` profile this package used to ship",
        "override the server command with `--profile lean`",
        "installs eleven lifecycle hooks",
    ):
        assert not LEAN_SURFACE_CLAIM.search(benign), benign
        assert not NO_HOOKS_CLAIM.search(benign), benign


def test_codex_security_doc_discloses_what_the_package_can_do() -> None:
    """A security doc that omits the destructive tools and the hooks gives a
    reviewer a materially wrong picture of the package's reach."""
    security = (PLUGIN_ROOT / "SECURITY.md").read_text(encoding="utf-8")

    for disclosure in ("forget", "wiki_purge", "full", "hooks"):
        assert disclosure in security, disclosure
    # The two hooks with effects beyond writing to the memory store.
    assert "decision_gate" in security, "the edit gate that can block a tool call"
    assert "session_lifecycle" in security, "the hook that spawns a detached process"
