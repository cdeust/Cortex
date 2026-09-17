#!/usr/bin/env python3
"""Claude Code hook script for SessionEnd events.

Problem Statement
-----------------
Profile updates should happen automatically when sessions end, without
requiring manual invocation of ``record_session_end``.

Approach
--------
Standalone script that reads hook event data from stdin (JSON), determines
the relevant domain, logs the session, and updates profiles via the
profile-builder module.

Installation
------------
Add to ``~/.claude/settings.json`` under hooks::

    {
        "hooks": {
            "SessionEnd": [{
                "command": "python -m mcp_server.hooks.session_lifecycle"
            }]
        }
    }

Invariants
----------
- Reads event from stdin (single JSON line)
- The session-log row is written before consolidation is spawned, and
  consolidation runs detached (this module re-invoked with
  ``--consolidate <mode>``, not awaited) — this process's own budget under
  Codex is 1 s soft / 3 s hard, well under a consolidation cycle's cost
- Non-blocking: exits quickly even if profile update fails
- Logs to stderr only
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

try:
    from mcp_server.core.profile_builder import apply_session_update
    from mcp_server.handlers.injection_receipts import (
        session_id_from_transcript,
    )
    from mcp_server.infrastructure.profile_store import (
        load_profiles,
        save_profile,
    )
    from mcp_server.infrastructure.session_store import (
        load_session_log,
        save_session_log,
    )
    from mcp_server.infrastructure.transcript_activity import transcript_activity
    from mcp_server.shared.categorizer import categorize
    from mcp_server.shared.log_rotation import methodology_log_path, open_rotating_log
    from mcp_server.shared.platform import python_executable
    from mcp_server.shared.project_ids import (
        cwd_to_project_id,
        domain_id_from_label,
        project_id_to_label,
    )
except ImportError as _imp_exc:
    _missing = str(_imp_exc).replace("No module named ", "").strip("'")
    print(
        f"[methodology-hook] Missing dependency '{_missing}'. "
        f"Run: python3 -m pip install -e /path/to/Cortex",
        file=sys.stderr,
    )
    sys.exit(1)

_LOG_PREFIX = "[methodology-hook]"

# Maximum number of sessions to retain in the session log.
MAX_SESSION_LOG_ENTRIES = 1000


def _log(msg: str) -> None:
    """Write a diagnostic message to stderr."""
    print(f"{_LOG_PREFIX} {msg}", file=sys.stderr)


def _resolve_domain(event: dict[str, Any], profiles: dict) -> str:
    """Determine domain ID from event data and existing profiles.

    Resolution order:
    1. Match *event.project* (or derived project ID from *event.cwd*) against
       known domain project lists.
    2. Fall back to label-based domain derivation.
    3. Default to ``"unknown"``.
    """
    proj_id = event.get("project") or cwd_to_project_id(event.get("cwd"))

    if proj_id:
        # Try matching against existing domain project lists
        for domain_id, domain in (profiles.get("domains") or {}).items():
            if proj_id in (domain.get("projects") or []):
                return domain_id

        # Derive from label
        label = project_id_to_label(proj_id)
        derived = domain_id_from_label(label)
        if derived:
            return derived

    return "unknown"


# source: ADR-0497
_SHORT_SESSION_TURNS = 5
# source: ADR-0497
_LONG_SESSION_TURNS = 20


def _consolidation_mode(turn_count: int) -> str:
    """Depth of the "dream" cycle a session of this length earns.

    Borbely 1982 (two-process model): consolidation pressure accumulates
    with waking activity. A short session gets the cheap decay-only pass;
    a long one gets decay + compress + CLS replay (McClelland et al. 1995).

    source: ADR-0497"""
    if turn_count < _SHORT_SESSION_TURNS:
        return "light"
    if turn_count < _LONG_SESSION_TURNS:
        return "standard"
    return "full"


_CONSOLIDATE_FLAG = "--consolidate"
# source: ADR-1082 — argv[0] (module) + _CONSOLIDATE_FLAG + <mode>
_CONSOLIDATE_ARGC = 3


def _spawn_consolidation(turn_count: int = 0) -> None:
    """Spawn the session's "dream" cycle as a detached subprocess and
    return without waiting on it, at the depth ``_consolidation_mode``
    selects. Re-invokes this module with ``--consolidate <mode>`` rather
    than ``consolidate_background`` (also a detached launcher): that
    module's cycle and stamp are SessionStart's periodic sweep, a
    different concern from a per-session turn-gated one (ADR-1082).

    precondition: the caller has already written the session-log row —
    everything from here runs outside SessionEnd's own timeout (Codex:
    1 s soft / 3 s hard, well under a consolidation cycle's cost).
    postcondition: a fully-detached subprocess (own process group, stdio
    -> ``consolidate.log``) exists; this returns before it has run
    anything. Never raises — a spawn failure is logged and swallowed,
    matching every other SessionEnd helper's non-fatal contract.

    source: ADR-1082"""
    mode = _consolidation_mode(turn_count)
    try:
        cmd = [
            python_executable(),
            "-m",
            "mcp_server.hooks.session_lifecycle",
            _CONSOLIDATE_FLAG,
            mode,
        ]
        log_path = methodology_log_path("consolidate.log")
        with open_rotating_log(log_path) as log:
            subprocess.Popen(  # noqa: S603 — cmd built from trusted sources
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        _log(f"consolidation spawned (mode={mode}) -> {log_path}")
    except Exception as exc:  # noqa: BLE001 — hook boundary — failure is logged to the hook log; the hook stays non-fatal
        _log(f"consolidation spawn failed (non-fatal): {exc}")


def _run_consolidation_cycle(mode: str) -> None:
    """Run one consolidation cycle at ``mode``'s depth — the body of the
    detached subprocess ``_spawn_consolidation`` starts.

    precondition: called from this module's own detached subprocess, after
    ``wire_composition_root`` has already run (same ``__main__`` guard
    every hook uses). postcondition: never raises past this function — a
    handler failure is logged and swallowed; nothing waits on this
    subprocess's exit code.

    source: ADR-1082"""
    args = {
        "light": {"decay": True, "compress": False},
        "standard": {"decay": True, "compress": True},
        "full": {"decay": True, "compress": True, "cls": True},
    }.get(mode, {"decay": True, "compress": False})
    try:
        from mcp_server.handlers.consolidate import handler as consolidate_handler  # noqa: PLC0415 — hook latency boundary: the per-event hook process defers the handler/store stack (hook boot ~0.05 s vs ~0.6 s registry import, measured 2026-07-28)

        result = asyncio.run(consolidate_handler(args))
        decayed = result.get("decay", {}).get("memories_decayed", 0)
        compressed = result.get("compression", {}).get(
            "compressed_to_gist", 0
        ) + result.get("compression", {}).get("compressed_to_tag", 0)
        cls_count = result.get("cls", {}).get("abstractions_created", 0)
        _log(
            f"Dream ({mode}): {decayed} decayed, {compressed} compressed"
            + (f", {cls_count} CLS abstractions" if cls_count else "")
        )
    except Exception as exc:  # noqa: BLE001 — detached subprocess boundary — nothing waits on this exit code
        _log(f"Consolidation failed (non-fatal): {exc}")


def _build_session_entry(event: dict[str, Any], domain_id: str) -> dict[str, Any]:
    """Build a session log entry from event data.

    precondition: ``event["session_id"]`` is present (enforced by
    ``process_event``'s guard before this is called). postcondition:
    ``sessionId`` is the transcript-stem canonical identity when
    ``event["transcript_path"]`` is a
    non-empty string; otherwise it degrades to the raw
    ``event["session_id"]`` — the documented divergence window (no
    transcript_path in the SessionEnd payload, e.g. synthetic/test
    events). No historical rows are rewritten; readers of session-log.json key on
    domain/tools/
    duration, not sessionId, so old-vs-new rows are read-compatible.

    source: ADR-0497"""
    keywords = event.get("keywords") or []
    tools = event.get("tools_used") or []
    turns = event.get("turn_count") or 0
    if not tools or not turns:
        # The SessionEnd payload carries neither; its transcript does
        # (ADR-1072).
        activity = transcript_activity(event.get("transcript_path"))
        tools = tools or activity["tool_sequence"]
        turns = turns or activity["turn_count"]
    return {
        "sessionId": session_id_from_transcript(event.get("transcript_path"))
        or event["session_id"],
        "domain": domain_id,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "project": event.get("project") or cwd_to_project_id(event.get("cwd")),
        "cwd": event.get("cwd"),
        "duration": event.get("duration"),
        "turnCount": turns,
        "toolsUsed": tools,
        "category": categorize(" ".join(keywords)) if keywords else "general",
        "entryKeywords": keywords,
    }


def _append_session(session_log: dict, entry: dict[str, Any]) -> None:
    """Append a session entry to the log, capping at MAX_SESSION_LOG_ENTRIES."""
    sessions = session_log.get("sessions") or []
    sessions.append(entry)
    if len(sessions) > MAX_SESSION_LOG_ENTRIES:
        sessions = sessions[-MAX_SESSION_LOG_ENTRIES:]
    session_log["sessions"] = sessions


def _tombstone_session_registry() -> None:
    """Best-effort SessionEnd write path (user arbitrage Q1, T2-D6
    extension): tombstones this window's registry entry so a handler
    call in the interstice before the next SessionStart resolves to
    NULL rather than the just-ended session — a false attribution is
    worse than a missing one (design §1 directing invariant).

    precondition: called from a SessionEnd hook's python process
    (``claude -> bash -> python`` chain, same as every other hook).
    postcondition: on success, this window's registry entry is
    tombstoned (lineage preserved, ``session_id`` becomes ``None`` on
    read). No-op when the ancestor ``claude`` pid cannot be resolved.
    Never raises — must not block the profile update / consolidation
    work that follows it.

    Independent of the event payload (unlike ``process_event`` below,
    which requires ``session_id``): the window ending is what matters
    here, not the event's content, so this runs even for a malformed
    or empty SessionEnd event.
    """
    try:
        from mcp_server.infrastructure.session_registry import (  # noqa: PLC0415 — hook latency boundary: the per-event hook process defers the handler/store stack (hook boot ~0.05 s vs ~0.6 s registry import, measured 2026-07-28)
            find_claude_ancestor,
            tombstone,
        )

        pid = find_claude_ancestor()
        if pid is not None:
            tombstone(pid)
    except Exception as exc:  # noqa: BLE001 — hook boundary — failure is logged to the hook log; the hook stays non-fatal
        _log(f"session registry tombstone skipped (non-fatal): {exc}")


def _deregister_groomer_coordinator() -> None:
    """Best-effort SessionEnd deregistration for the shared groomer (#171).

    precondition: called from a SessionEnd hook's python process — the same
    process whose pid ``SessionStart`` registered via ``os.getpid()``.
    postcondition: this session's registration is removed from the per-store
    ``GroomerCoordinator``; if it was the LAST live session, the groomer's
    single-instance marker is cleared (last-exit stop). Never raises — must
    not block the profile update / consolidation that follows.
    """
    try:
        from mcp_server.infrastructure.groomer_coordinator import (  # noqa: PLC0415 — hook latency boundary: the per-event hook process defers the handler/store stack (hook boot ~0.05 s vs ~0.6 s registry import, measured 2026-07-28)
            GroomerCoordinator,
            resolve_store_key,
        )

        coord = GroomerCoordinator(resolve_store_key())
        if coord.stop_if_last(os.getpid()):
            _log("groomer coordinator: last session exited, groomer stopped")
    except Exception as exc:  # noqa: BLE001 — hook boundary — failure is logged to the hook log; the hook stays non-fatal
        _log(f"groomer coordinator deregister skipped (non-fatal): {exc}")


def process_event(event: dict[str, Any] | None) -> None:
    """Process a single session lifecycle event.

    Parameters
    ----------
    event:
        Hook event data. Must contain at least ``session_id``.
        Optional fields: ``cwd``, ``project``, ``tools_used``, ``duration``,
        ``turn_count``, ``keywords``.
    """
    if not event or not event.get("session_id"):
        _log("No session_id in event, skipping")
        return

    profiles = load_profiles()
    log = load_session_log()

    domain_id = _resolve_domain(event, profiles)
    _append_session(log, _build_session_entry(event, domain_id))
    save_session_log(log)

    dp = (profiles.get("domains") or {}).get(domain_id)
    if dp:
        apply_session_update(
            domain_profile=dp,
            session_data={
                "duration": event.get("duration"),
                "tools_used": event.get("tools_used"),
                "turn_count": event.get("turn_count"),
            },
        )
        # D5: targeted per-domain write — does not rewrite other domains.
        save_profile(domain_id, dp)
        _log(f'Updated profile for domain "{domain_id}"')
    else:
        _log(f'No profile for domain "{domain_id}", logged session only')

    _spawn_consolidation(turn_count=event.get("turn_count", 0))


def main() -> None:
    """Entry point.

    ``argv[1] == "--consolidate"`` means this process is the detached
    subprocess ``_spawn_consolidation`` started — it runs the named
    cycle and returns, reading no stdin, since nothing spawned it with a
    SessionEnd event to process. Otherwise this is a normal SessionEnd
    invocation: read the JSON event from stdin and process it.
    """
    if len(sys.argv) >= _CONSOLIDATE_ARGC and sys.argv[1] == _CONSOLIDATE_FLAG:
        _run_consolidation_cycle(sys.argv[2])
        return

    # Registry tombstone (T2-H2) runs first and unconditionally: the
    # window ended regardless of whether stdin carries a usable event.
    _tombstone_session_registry()

    # Groomer coordinator deregistration (#171): decrement the session
    # count; last exit stops the shared groomer. Also unconditional and
    # independent of the event payload — the window ending is what matters.
    _deregister_groomer_coordinator()

    if sys.stdin.isatty():
        _log("No stdin data (TTY mode), exiting")
        return

    raw = sys.stdin.read().strip()
    if not raw:
        _log("Empty stdin, exiting")
        return

    try:
        event = json.loads(raw)
    except json.JSONDecodeError as exc:
        _log(f"Failed to parse event: {exc}")
        return

    process_event(event)


if __name__ == "__main__":
    # No-op inside the headless wiki-authoring subprocess (see
    # _headless_guard): prevents recursion + memory pollution when
    # ``claude -p --setting-sources user`` loads the user hooks.
    from mcp_server.hooks._headless_guard import (
        exit_if_headless_authoring_child,
    )
    from mcp_server.hooks._store_lifecycle import close_shared_store_on_exit

    exit_if_headless_authoring_child()
    from mcp_server.hooks.wiring import wire_composition_root  # noqa: PLC0415 — source: issue #560

    wire_composition_root()
    # source: ADR-0497
    with close_shared_store_on_exit():
        main()
