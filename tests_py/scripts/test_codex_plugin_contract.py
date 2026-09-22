"""Contract tests for the isolated, full-parity Codex plugin package."""

from __future__ import annotations

import json
import re
from pathlib import Path

from mcp_server.hooks.entry import HOOK_MODULES


REPO_ROOT = Path(__file__).resolve().parents[2]
MARKETPLACE_PATH = REPO_ROOT / ".agents/plugins/marketplace.json"
PLUGIN_ROOT = REPO_ROOT / "plugins/hypermnesia-mcp-codex"
PLUGIN_PATH = PLUGIN_ROOT / ".codex-plugin/plugin.json"
MCP_PATH = PLUGIN_ROOT / ".mcp.json"
HOOKS_REF = "./hooks/hooks.json"
HOOKS_PATH = PLUGIN_ROOT / "hooks/hooks.json"
CLAUDE_PLUGIN_PATH = REPO_ROOT / ".claude-plugin/plugin.json"

# The console script mcp_server/hooks/entry.py backs (pyproject.toml). A Codex
# plugin ships only its own directory, so it can call neither this repository
# nor scripts/launcher.py.
HOOK_CONSOLE_SCRIPT = "hypermnesia-mcp-hook"
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


def test_codex_hooks_dispatch_exactly_the_entry_point_allowlist() -> None:
    """The regression guard: the Codex manifest wires every hook module the
    console script allows, and nothing the console script would refuse.

    HOOK_MODULES is imported rather than restated, so a module added to (or
    dropped from) the allowlist cannot silently leave the Codex package
    behind the Claude one.
    """
    dispatched = {
        module
        for entries in _json(HOOKS_PATH)["hooks"].values()
        for entry in entries
        for hook in entry["hooks"]
        for module in HOOK_MODULES
        if hook["command"].endswith(f"{HOOK_CONSOLE_SCRIPT} {module}'")
    }
    assert dispatched == set(HOOK_MODULES)


def test_codex_hook_commands_run_the_published_wheel_not_this_repository() -> None:
    """A Codex plugin ships only its own directory: no scripts/launcher.py,
    no ${CLAUDE_PLUGIN_ROOT}-relative path, and a named diagnostic when the
    one thing this command line depends on (uvx) is absent."""
    for entries in _json(HOOKS_PATH)["hooks"].values():
        for entry in entries:
            for hook in entry["hooks"]:
                command = hook["command"]
                assert hook["type"] == "command"
                assert "scripts/launcher.py" not in command
                assert "CLAUDE_PLUGIN_ROOT" not in command
                assert "command -v uvx" in command
                assert 'uvx --from "hypermnesia-mcp[postgresql,sqlite]"' in command


def test_codex_hooks_use_codex_event_names_and_widened_matchers() -> None:
    """Event names are Codex's own (learn.chatgpt.com/docs/hooks, read
    2026-09-22), and matchers carry Codex's native tool names alongside
    Claude's."""
    hooks = _json(HOOKS_PATH)["hooks"]

    # Codex has no Notification event; PreCompact is where a checkpoint taken
    # *before* compaction belongs (compaction_checkpoint's own contract).
    assert "Notification" not in hooks
    assert "PreCompact" in hooks
    assert set(hooks) == {
        "PreToolUse",
        "SessionStart",
        "UserPromptSubmit",
        "PostToolUse",
        "SessionEnd",
        "PreCompact",
        "SubagentStart",
    }

    def _matcher_for(module: str) -> str | None:
        for entries in hooks.values():
            for entry in entries:
                for hook in entry["hooks"]:
                    if hook["command"].endswith(f"{HOOK_CONSOLE_SCRIPT} {module}'"):
                        return entry.get("matcher")
        raise AssertionError(f"{module} is not wired")

    # host_event.py expands apply_patch into Edit/Write events, so every
    # edit-triggered hook must see the apply_patch call in the first place.
    for module in ("decision_gate", "no_deps_gate", "preemptive_context"):
        assert "apply_patch" in (_matcher_for(module) or "")
    assert "apply_patch" in (_matcher_for("pipeline_impact_bump") or "")
    # host_event.py maps exec_command/shell_command onto a Bash-shaped event.
    bash_matcher = _matcher_for("post_commit_reindex") or ""
    for shell_tool in ("Bash", "exec_command", "shell_command"):
        assert shell_tool in bash_matcher
    # Claude's PostToolUse capture matcher is "*"; Codex documents "*" as a
    # universal matcher too.
    assert _matcher_for("post_tool_capture") == "*"


def test_codex_session_end_respects_the_host_timeout_ceiling() -> None:
    """Codex defaults SessionEnd to 1s and supports up to 3s
    (learn.chatgpt.com/docs/hooks, read 2026-09-22), so the Claude manifest's
    30s is not expressible here. Every other hook omits `timeout` and takes
    Codex's own 600s default rather than an unmeasured number."""
    hooks = _json(HOOKS_PATH)["hooks"]
    session_end = hooks["SessionEnd"][0]["hooks"][0]
    assert session_end["timeout"] == 3

    for event, entries in hooks.items():
        if event == "SessionEnd":
            continue
        for entry in entries:
            for hook in entry["hooks"]:
                assert "timeout" not in hook


def test_codex_wires_the_same_hook_modules_as_the_claude_plugin() -> None:
    """Parity is the point: neither host gets a hook the other does not."""
    claude_hooks = _json(CLAUDE_PLUGIN_PATH)["hooks"]
    claude_modules = {
        module
        for entries in claude_hooks.values()
        for entry in entries
        for hook in entry["hooks"]
        for module in HOOK_MODULES
        if hook["command"].endswith(f"mcp_server.hooks.{module}'")
    }
    assert claude_modules == set(HOOK_MODULES)


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
