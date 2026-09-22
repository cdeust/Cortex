"""Contract tests for the isolated, full-parity Codex plugin package.

The hook manifest this package now ships has its own contracts in the sibling
test_codex_plugin_hooks_contract.py; this file carries the package identity,
the marketplace entries and the MCP server command.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MARKETPLACE_PATH = REPO_ROOT / ".agents/plugins/marketplace.json"
PLUGIN_ROOT = REPO_ROOT / "plugins/hypermnesia-mcp-codex"
PLUGIN_PATH = PLUGIN_ROOT / ".codex-plugin/plugin.json"
MCP_PATH = PLUGIN_ROOT / ".mcp.json"
HOOKS_REF = "./hooks/hooks.json"
HOOKS_PATH = PLUGIN_ROOT / "hooks/hooks.json"
CLAUDE_PLUGIN_PATH = REPO_ROOT / ".claude-plugin/plugin.json"
CLAUDE_MARKETPLACE_PATH = REPO_ROOT / ".claude-plugin/marketplace.json"
VIZ_SHIM_ROOT = REPO_ROOT / "plugins/cortex-viz-deprecated"
VIZ_SHIM_PLUGIN_PATH = VIZ_SHIM_ROOT / ".claude-plugin/plugin.json"
VIZ_SHIM_HOOKS_PATH = VIZ_SHIM_ROOT / "hooks/hooks.json"

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
LEAN_SURFACE_CLAIM = re.compile(r"\b(?:10|ten)[- ]tool\b", re.IGNORECASE)


def _json(path: Path) -> dict:
    return json.loads(path.read_text())


def test_codex_plugin_is_confined_to_a_dedicated_subdirectory() -> None:
    """Never reintroduce the project-scoped MCP collision in Claude Code."""
    assert not (REPO_ROOT / ".mcp.json").exists()
    assert not (REPO_ROOT / ".codex-plugin").exists()
    assert PLUGIN_PATH.is_file()
    assert MCP_PATH.is_file()

    ignored = (REPO_ROOT / ".mcpbignore").read_text().splitlines()
    assert ".agents/" in ignored
    # The directory entry already excludes hooks/hooks.json and anything else
    # added under the package, so a new file there never needs its own line.
    assert "plugins/hypermnesia-mcp-codex/" in ignored
    assert HOOKS_PATH.is_relative_to(PLUGIN_ROOT)
    assert "plugins/cortex-deprecated/" in ignored
    assert "plugins/cortex-viz-deprecated/" in ignored


def test_codex_marketplace_resolves_only_the_dedicated_plugin() -> None:
    marketplace = _json(MARKETPLACE_PATH)
    assert marketplace["name"] == "cortex-codex-plugins"
    assert len(marketplace["plugins"]) == 1

    entry = marketplace["plugins"][0]
    assert entry == {
        "name": "hypermnesia-mcp-codex",
        "source": {
            "source": "local",
            "path": "./plugins/hypermnesia-mcp-codex",
        },
        "policy": {
            "installation": "AVAILABLE",
            "authentication": "ON_INSTALL",
        },
        "category": "Developer Tools",
    }
    source = (REPO_ROOT / entry["source"]["path"]).resolve()
    assert source == PLUGIN_ROOT.resolve()
    assert source.is_relative_to(REPO_ROOT.resolve())


def test_codex_plugin_serves_the_full_profile_and_references_its_hooks() -> None:
    plugin = _json(PLUGIN_PATH)
    server = _json(MCP_PATH)["mcpServers"]["cortex"]

    assert plugin["name"] == "hypermnesia-mcp-codex"
    # Both host surfaces are path references, never inlined objects.
    assert plugin["mcpServers"] == "./.mcp.json"
    assert plugin["hooks"] == HOOKS_REF
    assert (PLUGIN_ROOT / HOOKS_REF).resolve() == HOOKS_PATH.resolve()

    assert server == {
        "command": "uvx",
        "args": [
            "--from",
            "hypermnesia-mcp[postgresql,sqlite]",
            "hypermnesia-mcp",
        ],
        # Codex's local storage selection has the same auto contract as the
        # DB-optional sandbox surface: try PostgreSQL first and fall back only
        # when no explicit DATABASE_URL was supplied.
        "env": {"CORTEX_RUNTIME": "cowork"},
        # Re-measured for the full profile on 2026-09-22 with
        # scripts/verify_mcp_hosts.py (the command CI runs): initialize +
        # tools/list + memory_stats over 59 tools in 120.17s from clean
        # UV_CACHE_DIR / UV_TOOL_DIR on macOS 26.6.2 arm64 with uv 0.11.3;
        # 4.24s on the next run from that cache. This bounded ceiling leaves
        # startup headroom without a sleep or a retry.
        "startup_timeout_sec": 180,
    }
    # No --profile flag at all, exactly like the Claude plugin's server args:
    # the default full profile is what both hosts get.
    assert "--profile" not in server["args"]


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


def test_codex_security_doc_discloses_what_the_package_can_do() -> None:
    """A security doc that omits the destructive tools and the hooks gives a
    reviewer a materially wrong picture of the package's reach."""
    security = (PLUGIN_ROOT / "SECURITY.md").read_text(encoding="utf-8")

    for disclosure in ("forget", "wiki_purge", "full", "hooks"):
        assert disclosure in security, disclosure
    # The two hooks with effects beyond writing to the memory store.
    assert "decision_gate" in security, "the edit gate that can block a tool call"
    assert "session_lifecycle" in security, "the hook that spawns a detached process"


def test_codex_package_does_not_weaken_the_claude_plugin() -> None:
    """Parity was reached by raising Codex, never by lowering Claude Code:
    the Claude manifest still launches through its own launcher, keeps its
    agents, and carries no --profile flag."""
    claude = _json(CLAUDE_PLUGIN_PATH)
    claude_server = claude["mcpServers"]["cortex"]

    assert claude["name"] == "hypermnesia-mcp"
    assert claude["hooks"]
    assert claude["agents"] == ["./claude-agents/cortex-wiki-groomer.md"]
    assert claude_server["command"] == "python3"
    assert claude_server["args"] == [
        "${CLAUDE_PLUGIN_ROOT}/scripts/launcher.py",
        "mcp_server",
    ]
    assert "--profile" not in claude_server["args"]
    # The Codex package is still confined to its own directory: it adds no
    # launcher of its own and touches nothing the Claude bundle ships.
    assert not (PLUGIN_ROOT / "scripts").exists()


def test_claude_marketplace_publishes_pinned_canonical_viz_identity() -> None:
    marketplace = _json(CLAUDE_MARKETPLACE_PATH)
    entries = {entry["name"]: entry for entry in marketplace["plugins"]}
    canonical = entries["hypermnesia-mcp-viz"]

    # "3.0.0"/1c1940e... was the dangling pin from the #179-style incident:
    # cortex-viz never tagged a v3.0.0 (the rename landed straight on main
    # without a release), so the entry carried a sha and NO `ref` — a commit
    # nobody had released, advertised as a version.
    #
    # This asserts the invariant that defect broke, not the literal triple it
    # was fixed to. A frozen version/ref/sha has to be hand-edited on every
    # legitimate pin move, which makes it a change detector rather than a
    # guard: it adds no detection the manifest's own diff does not already
    # give, and adds a second place to get wrong. Whether the tag actually
    # exists upstream is a network question, answered by
    # scripts/check_marketplace_pins.py on every manifest PR and weekly cron.
    source = canonical["source"]
    assert source["source"] == "github"
    assert source["repo"] == "cdeust/cortex-viz"
    assert source["ref"] == f"v{canonical['version']}", (
        "a release pin names its tag; a sha with no ref, or a ref that "
        "disagrees with the advertised version, is the #179 defect"
    )
    assert re.fullmatch(r"[0-9a-f]{40}", source["sha"]), (
        "pin the full commit sha — an abbreviated or symbolic value silently "
        "re-resolves when the branch moves"
    )
    assert "standalone Hypermnesia MCP Viz server" in canonical["description"]


def test_legacy_viz_identity_is_a_frozen_nonfunctional_migration_shim() -> None:
    marketplace = _json(CLAUDE_MARKETPLACE_PATH)
    entries = {entry["name"]: entry for entry in marketplace["plugins"]}
    legacy = entries["cortex-viz"]
    plugin = _json(VIZ_SHIM_PLUGIN_PATH)
    hooks = _json(VIZ_SHIM_HOOKS_PATH)

    assert legacy["version"] == "2.8.0"
    assert legacy["source"] == "./plugins/cortex-viz-deprecated"
    assert "nonfunctional migration shim" in legacy["description"]
    assert plugin["name"] == "cortex-viz"
    assert plugin["version"] == legacy["version"]
    for functional_surface in ("mcpServers", "skills", "commands", "agents"):
        assert functional_surface not in plugin

    assert not (VIZ_SHIM_ROOT / ".mcp.json").exists()
    assert set(hooks["hooks"]) == {"SessionStart"}
    notice = hooks["hooks"]["SessionStart"][0]["hooks"][0]
    assert notice["type"] == "command"
    assert "cortex-viz@cortex-plugins" in notice["command"]
    assert "hypermnesia-mcp-viz@cortex-plugins" in notice["command"]


def test_readme_carries_the_complete_viz_and_spec_identity_migrations() -> None:
    readme = (REPO_ROOT / "README.md").read_text()

    assert "claude plugin uninstall cortex-viz@cortex-plugins" in readme
    assert "claude plugin install hypermnesia-mcp-viz@cortex-plugins" in readme
    for tool in ("open_visualization", "get_methodology_graph"):
        old_name = f"mcp__plugin_cortex-viz_cortex-viz__{tool}"
        new_name = f"mcp__plugin_hypermnesia-mcp-viz_hypermnesia-mcp-viz__{tool}"
        assert old_name in readme
        assert new_name in readme

    assert "ai-architect-mcp-spec" in readme
    assert "prd-spec-generator" not in readme


def test_current_companion_docs_use_canonical_publication_identities() -> None:
    readme = (REPO_ROOT / "README.md").read_text()
    assert (
        '<a href="https://github.com/cdeust/cortex-viz">hypermnesia-mcp-viz</a>'
        in readme
    )

    current_docs = [
        REPO_ROOT / "docs/api-reference.md",
        REPO_ROOT / "docs/mcp-connections.example.json",
        REPO_ROOT / "docs/mcp-tools.md",
        REPO_ROOT / "docs/module-inventory.md",
    ]
    for path in current_docs:
        content = path.read_text()
        assert "prd-spec-generator" not in content
        assert "**cortex-viz** MCP" not in content
        assert "Install cortex-viz" not in content
