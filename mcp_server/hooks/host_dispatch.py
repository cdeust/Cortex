"""Turn one stdin payload into the per-event runs ``entry.py`` dispatches.

Split out of ``entry.py`` to keep that module a thin allowlist-and-wire
composition root (its own size budget is 150 lines; this module carries the
event-derivation and per-run mechanics it delegates to).
"""

from __future__ import annotations

import io
import json
import runpy
import sys

from mcp_server.hooks.host_event import HostEventError, normalize_event

# Hook classes that block a tool call by exiting non-zero, per
# .claude-plugin/plugin.json: decision_gate and no_deps_gate are the only
# PreToolUse hooks in entry.HOOK_MODULES, and both already fail closed.
PRE_TOOL_USE = "PreToolUse"


def run_event(module: str, payload: str) -> int:
    """Run ``module`` as ``__main__`` against one derived stdin payload; its
    exit code, or 1 with a stderr line for any exception it left uncaught."""
    sys.argv = [module]
    sys.stdin = io.StringIO(payload)
    try:
        runpy.run_module(module, run_name="__main__", alter_sys=True)
    except SystemExit as exc:
        return 0 if exc.code is None else int(exc.code)
    except Exception as exc:  # noqa: BLE001 - dispatch boundary; reported, never crashes
        print(f"[hypermnesia-mcp-hook] Failed to run {module}: {exc}", file=sys.stderr)
        return 1
    return 0


def derive_events(module: str, raw: str) -> tuple[list[str], str | None, str | None]:
    """Stdin payloads to dispatch, the source event's ``hook_event_name``,
    and its ``cwd``.

    Precondition: ``raw`` is the exact stdin text. Postcondition: empty or
    non-JSON stdin is returned as a single unmodified payload so each
    hook's own tolerant stdin parsing still applies; a JSON object is
    normalized into one payload per derived event. Exits 2 (PreToolUse) or
    1 (otherwise) with a stderr line when the event is well-formed JSON but
    cannot be normalized without losing edit information, matching how the
    edit gates already fail closed.
    """
    stripped = raw.strip()
    if not stripped:
        return [raw], None, None
    try:
        event = json.loads(stripped)
    except json.JSONDecodeError:
        return [raw], None, None
    if not isinstance(event, dict):
        return [raw], None, None
    hook_event_name = event.get("hook_event_name")
    try:
        derived = normalize_event(event)
    except HostEventError as exc:
        print(f"[hypermnesia-mcp-hook] {module}: {exc}", file=sys.stderr)
        sys.exit(2 if hook_event_name == PRE_TOOL_USE else 1)
    return [json.dumps(e) for e in derived], hook_event_name, event.get("cwd")
