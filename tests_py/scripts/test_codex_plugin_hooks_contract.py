"""Contract tests for the Codex plugin's lifecycle-hook manifest.

Split out of test_codex_plugin_contract.py, which carries the package's
identity, marketplace and MCP-server contracts; this file carries the hook
wiring added when Codex reached full parity with Claude Code. The two files
assert different artifacts (hooks/hooks.json here, .mcp.json and the
marketplace entries there) and the seam keeps each under the 300-line cap.
"""

from __future__ import annotations

import json
from pathlib import Path

from mcp_server.hooks.entry import HOOK_MODULES


REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = REPO_ROOT / "plugins/hypermnesia-mcp-codex"
HOOKS_PATH = PLUGIN_ROOT / "hooks/hooks.json"
CLAUDE_PLUGIN_PATH = REPO_ROOT / ".claude-plugin/plugin.json"

# The console script mcp_server/hooks/entry.py backs (pyproject.toml). A Codex
# plugin ships only its own directory, so it can call neither this repository
# nor scripts/launcher.py.
HOOK_CONSOLE_SCRIPT = "hypermnesia-mcp-hook"

# Codex's own event vocabulary for the hooks Cortex wires, verified against
# learn.chatgpt.com/docs/hooks (read 2026-09-22). Notably absent: Notification,
# which Codex does not have at all.
CODEX_EVENTS = {
    "PreToolUse",
    "SessionStart",
    "UserPromptSubmit",
    "PostToolUse",
    "SessionEnd",
    "PreCompact",
    "SubagentStart",
}


def _json(path: Path) -> dict:
    return json.loads(path.read_text())


def _hooks() -> dict:
    return _json(HOOKS_PATH)["hooks"]


def _every_hook(hooks: dict):
    """(event, entry, hook) for every command the manifest declares."""
    for event, entries in hooks.items():
        for entry in entries:
            for hook in entry["hooks"]:
                yield event, entry, hook


def _dispatched(hooks: dict, suffix: str) -> set[str]:
    """Allowlisted module names the manifest's commands dispatch to."""
    return {
        module
        for _event, _entry, hook in _every_hook(hooks)
        for module in HOOK_MODULES
        if hook["command"].endswith(suffix.format(module=module))
    }


def test_codex_hooks_dispatch_exactly_the_entry_point_allowlist() -> None:
    """The regression guard: the Codex manifest wires every hook module the
    console script allows, and nothing the console script would refuse.

    HOOK_MODULES is imported rather than restated, so a module added to (or
    dropped from) the allowlist cannot silently leave the Codex package
    behind the Claude one.
    """
    dispatched = _dispatched(_hooks(), HOOK_CONSOLE_SCRIPT + " {module}'")
    assert dispatched == set(HOOK_MODULES)


def test_codex_hook_commands_run_the_published_wheel_not_this_repository() -> None:
    """A Codex plugin ships only its own directory: no scripts/launcher.py,
    no ${CLAUDE_PLUGIN_ROOT}-relative path, and a named diagnostic when the
    one thing this command line depends on (uvx) is absent."""
    for _event, _entry, hook in _every_hook(_hooks()):
        command = hook["command"]
        assert hook["type"] == "command"
        assert "scripts/launcher.py" not in command
        assert "CLAUDE_PLUGIN_ROOT" not in command
        assert "command -v uvx" in command
        assert 'uvx --from "hypermnesia-mcp[postgresql,sqlite]"' in command


def test_codex_hooks_use_only_codex_event_names() -> None:
    """Codex has no Notification event; PreCompact is where a checkpoint taken
    before compaction belongs, which is compaction_checkpoint's own contract.
    PostCompact is deliberately not wired: it would checkpoint the same
    compaction a second time."""
    hooks = _hooks()
    assert "Notification" not in hooks
    assert "PostCompact" not in hooks
    assert set(hooks) == CODEX_EVENTS


def test_codex_matchers_carry_the_native_tool_names_host_event_translates() -> None:
    """Matchers must admit the Codex tool names, or mcp_server/hooks/
    host_event.py never receives the events it exists to translate."""
    hooks = _hooks()

    def _matcher_for(module: str) -> str:
        for _event, entry, hook in _every_hook(hooks):
            if hook["command"].endswith(f"{HOOK_CONSOLE_SCRIPT} {module}'"):
                return entry.get("matcher") or ""
        raise AssertionError(f"{module} is not wired")

    # host_event.py expands apply_patch into Edit/Write events, so every
    # edit-triggered hook must see the apply_patch call in the first place.
    edit_triggered = (
        "decision_gate",
        "no_deps_gate",
        "preemptive_context",
        "pipeline_impact_bump",
    )
    for module in edit_triggered:
        assert "apply_patch" in _matcher_for(module), module
    # host_event.py maps exec_command/shell_command onto a Bash-shaped event.
    bash_matcher = _matcher_for("post_commit_reindex")
    for shell_tool in ("Bash", "exec_command", "shell_command"):
        assert shell_tool in bash_matcher, shell_tool
    # Claude's PostToolUse capture matcher is "*"; Codex documents "*" as a
    # universal matcher too.
    assert _matcher_for("post_tool_capture") == "*"


def test_codex_session_end_respects_the_host_timeout_ceiling() -> None:
    """Codex defaults SessionEnd to 1s and supports up to 3s
    (learn.chatgpt.com/docs/hooks, read 2026-09-22), so the Claude manifest's
    30s is not expressible here. Every other hook omits `timeout` and takes
    Codex's own 600s default rather than an unmeasured number."""
    hooks = _hooks()
    assert hooks["SessionEnd"][0]["hooks"][0]["timeout"] == 3

    for event, _entry, hook in _every_hook(hooks):
        if event != "SessionEnd":
            assert "timeout" not in hook, event


def test_codex_wires_the_same_hook_modules_as_the_claude_plugin() -> None:
    """Parity is the point: neither host gets a hook the other does not."""
    claude = _dispatched(
        _json(CLAUDE_PLUGIN_PATH)["hooks"], "mcp_server.hooks.{module}'"
    )
    assert claude == set(HOOK_MODULES)
    assert claude == _dispatched(_hooks(), HOOK_CONSOLE_SCRIPT + " {module}'")
