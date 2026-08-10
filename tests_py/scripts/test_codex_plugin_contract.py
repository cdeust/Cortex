"""Contract tests for the additive, isolated Codex plugin package."""

from __future__ import annotations

import json
import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MARKETPLACE_PATH = REPO_ROOT / ".agents/plugins/marketplace.json"
PLUGIN_ROOT = REPO_ROOT / "plugins/hypermnesia-mcp-codex"
PLUGIN_PATH = PLUGIN_ROOT / ".codex-plugin/plugin.json"
MCP_PATH = PLUGIN_ROOT / ".mcp.json"
CLAUDE_MARKETPLACE_PATH = REPO_ROOT / ".claude-plugin/marketplace.json"
VIZ_SHIM_ROOT = REPO_ROOT / "plugins/cortex-viz-deprecated"
VIZ_SHIM_PLUGIN_PATH = VIZ_SHIM_ROOT / ".claude-plugin/plugin.json"
VIZ_SHIM_HOOKS_PATH = VIZ_SHIM_ROOT / "hooks/hooks.json"


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
    assert "plugins/hypermnesia-mcp-codex/" in ignored
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


def test_codex_plugin_is_mcp_only_and_uses_the_exact_lean_profile() -> None:
    plugin = _json(PLUGIN_PATH)
    server = _json(MCP_PATH)["mcpServers"]["cortex"]

    assert plugin["name"] == "hypermnesia-mcp-codex"
    assert plugin["mcpServers"] == "./.mcp.json"
    for unsupported in ("hooks", "skills", "apps", "agents", "postInstall"):
        assert unsupported not in plugin

    assert server == {
        "command": "uvx",
        "args": [
            "--from",
            "hypermnesia-mcp[postgresql,sqlite]",
            "hypermnesia-mcp",
            "--profile",
            "lean",
        ],
        # Codex is additive, but its local storage selection has the same
        # auto contract as the DB-optional sandbox surface: try PostgreSQL
        # first and fall back only when no explicit DATABASE_URL was supplied.
        "env": {"CORTEX_RUNTIME": "cowork"},
        # Measured clean-cache startup with both extras on 2026-08-03: 103.84s
        # on macOS 26.5.1 arm64 with uv 0.8.19. This bounded ceiling leaves
        # startup headroom without inventing a sleep or retry.
        "startup_timeout_sec": 180,
    }


def test_codex_package_does_not_weaken_the_primary_claude_plugin() -> None:
    claude = _json(REPO_ROOT / ".claude-plugin/plugin.json")
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
