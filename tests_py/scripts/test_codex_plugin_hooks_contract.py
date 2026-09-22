"""Contract tests for the Codex plugin's lifecycle-hook manifest.

Split out of test_codex_plugin_contract.py, which carries the package's
identity, marketplace and MCP-server contracts; this file carries the hook
wiring added when Codex reached full parity with Claude Code. The two files
assert different artifacts (hooks/hooks.json here, .mcp.json and the
marketplace entries there) and the seam keeps each under the 300-line cap.
"""

from __future__ import annotations

from mcp_server.hooks.entry import HOOK_MODULES

from tests_py.scripts._codex_plugin_support import (
    CLAUDE_SUFFIX,
    CODEX_SUFFIX,
    PLUGIN_PATH,
    read_json as _json,
    claude_hooks,
    codex_hooks,
    every_hook,
    hook_index,
)

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

# source: learn.chatgpt.com/docs/hooks (read 2026-09-22) -- "SessionEnd and
# Interrupt use 1 second by default and support up to 3 seconds." Every other
# event takes 600s when `timeout` is omitted, with no documented maximum, so
# every other budget is settable and comes from the Claude manifest instead.
#
# Codex limits intake to three seconds. The bundled script persists before
# package startup; session/profile recording runs in a replayable worker.
CODEX_SESSION_END_MAX = 3  # source: ADR-1084


def test_codex_hooks_dispatch_exactly_the_entry_point_allowlist() -> None:
    """The regression guard: the Codex manifest wires every hook module the
    console script allows, and nothing the console script would refuse.

    HOOK_MODULES is imported rather than restated, so a module added to (or
    dropped from) the allowlist cannot silently leave the Codex package
    behind the Claude one.
    """
    assert set(hook_index(codex_hooks(), CODEX_SUFFIX)) == set(HOOK_MODULES)


def test_codex_hook_commands_run_the_published_wheel_not_this_repository() -> None:
    """A Codex plugin ships only its own directory: no scripts/launcher.py,
    no ${CLAUDE_PLUGIN_ROOT}-relative path, and a named diagnostic when the
    one thing this command line depends on (uvx) is absent."""
    for event, _entry, hook in every_hook(codex_hooks()):
        command = hook["command"]
        assert hook["type"] == "command"
        assert "scripts/launcher.py" not in command
        assert "CLAUDE_PLUGIN_ROOT" not in command
        if event == "SessionEnd":
            assert command == 'python3 "${PLUGIN_ROOT}/scripts/session_queue.py" intake'
            continue
        assert "command -v uvx" in command
        version = _json(PLUGIN_PATH)["version"]
        assert f'uvx --from "hypermnesia-mcp[postgresql,sqlite]=={version}"' in command


def test_codex_hooks_use_only_codex_event_names() -> None:
    """Codex has no Notification event; PreCompact is where a checkpoint taken
    before compaction belongs, which is compaction_checkpoint's own contract.
    PostCompact is deliberately not wired: it would checkpoint the same
    compaction a second time."""
    hooks = codex_hooks()
    assert "Notification" not in hooks
    assert "PostCompact" not in hooks
    assert set(hooks) == CODEX_EVENTS


def test_codex_matchers_carry_the_native_tool_names_host_event_translates() -> None:
    """Matchers must admit the Codex tool names, or mcp_server/hooks/
    host_event.py never receives the events it exists to translate."""
    index = hook_index(codex_hooks(), CODEX_SUFFIX)

    def matcher_for(module: str) -> str:
        assert module in index, f"{module} is not wired"
        return index[module][1].get("matcher") or ""

    # host_event.py expands apply_patch into Edit/Write events, so every
    # edit-triggered hook must see the apply_patch call in the first place.
    edit_triggered = (
        "decision_gate",
        "no_deps_gate",
        "preemptive_context",
        "pipeline_impact_bump",
    )
    for module in edit_triggered:
        assert "apply_patch" in matcher_for(module), module
    # host_event.py maps exec_command/shell_command onto a Bash-shaped event.
    bash_matcher = matcher_for("post_commit_reindex")
    for shell_tool in ("Bash", "exec_command", "shell_command"):
        assert shell_tool in bash_matcher, shell_tool
    # Claude's PostToolUse capture matcher is "*"; Codex documents "*" as a
    # universal matcher too.
    assert matcher_for("post_tool_capture") == "*"


def test_codex_hook_timeouts_mirror_the_claude_manifest() -> None:
    """Parity is the point, and a latency budget is part of behaviour.

    Leaving these unset takes Codex's 600s default: a stalled `uvx` resolve
    on `UserPromptSubmit` would hold up every prompt for ten minutes where
    Claude caps the same hook at 5s. Codex documents a special default and
    maximum only for SessionEnd and Interrupt, so every other budget here is
    Claude's own number (learn.chatgpt.com/docs/hooks, read 2026-09-22).

    A `None` on either side means that manifest declares no budget and the
    hook takes its host's command-hook default, which is 600s on both
    (code.claude.com/docs hooks reference and learn.chatgpt.com/docs/hooks,
    both read 2026-09-22), so declaring nothing on both sides is parity too.
    """
    claude = {
        module: hook.get("timeout")
        for module, (_event, _entry, hook) in hook_index(
            claude_hooks(), CLAUDE_SUFFIX
        ).items()
    }
    codex = {
        module: (event, hook.get("timeout"))
        for module, (event, _entry, hook) in hook_index(
            codex_hooks(), CODEX_SUFFIX
        ).items()
    }
    assert set(codex) == set(claude)

    for module, (event, timeout) in codex.items():
        if event == "SessionEnd":
            # The one budget Codex will not accept; see CODEX_SESSION_END_MAX.
            assert timeout == CODEX_SESSION_END_MAX, module
            assert claude[module] > CODEX_SESSION_END_MAX, (
                "SessionEnd is only special-cased because Claude's budget "
                "exceeds the Codex maximum; it no longer does"
            )
        else:
            assert timeout == claude[module], module


def test_codex_wires_the_same_hook_modules_as_the_claude_plugin() -> None:
    """Parity is the point: neither host gets a hook the other does not."""
    claude = set(hook_index(claude_hooks(), CLAUDE_SUFFIX))
    assert claude == set(HOOK_MODULES)
    assert claude == set(hook_index(codex_hooks(), CODEX_SUFFIX))
