#!/usr/bin/env python3
"""Zero-ops install check: the owner's commands on a clean machine.

    claude plugin marketplace add <checkout | cdeust/Cortex>
    claude plugin install hypermnesia-mcp@cortex-plugins
    claude --init-only      (through scripts/init_plugin.py: the Setup hook
                             installs every set and the model, and a failure
                             exits non-zero)
    first session  -> SessionStart says "Cortex ready", tools answer,
                      remember -> recall works; no hook installed anything
    second session -> "Cortex ready"

Run on an isolated HOME / ``CLAUDE_CONFIG_DIR`` with the real Claude Code CLI:
``claude --init-only`` runs the plugin's SessionStart hook under the host's own
timeout while ``claude mcp list`` connects the plugin's MCP server, both at
once as a first session does. The MCP server is then driven over stdio for
remember -> recall. After every plugin process has exited (background
installs included, bounded), a second session must also say "Cortex ready".
Prints one JSON report; exit 0 only when every check passes.

Usage:
    python3 scripts/install_e2e/run.py --marketplace SRC --work DIR
        [--python /usr/bin/python3] [--x86_64] [--settle-seconds N]

source: ADR-1104
source: ADR-1108
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import shutil
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evidence  # noqa: E402
import host  # noqa: E402
import mcp_session  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import init_plugin  # noqa: E402 — scripts/ is a sibling of this package

# source: mcp_server/hooks/session_start_status.py semantic_clause
SEMANTIC_ON = "semantic search on"
# source: mcp_server/hooks/session_start.py (the store the status line names)
MANAGED_STORE = "PostgreSQL memory store"
_SERVER_LINE = re.compile(r"plugin:hypermnesia-mcp:cortex: .* - (.*)")
# A first session's server installs before its tools exist (ADR-1104).
STDIO_BOUND_SECONDS = 1500  # source: ADR-1104 (cold install measured 117 s)
# An interactive prompt would block a command whose stdin is closed; these are
# the host's informational install-summary lines, kept verbatim in the report.
_NOTICES = re.compile(r"not yet set|/plugin configure|--config", re.IGNORECASE)


def _session_start_timeout_ms(root: str | None) -> int | None:
    """The SessionStart hook timeout the installed manifest declares."""
    if not root:
        return None
    manifest = json.loads((Path(root) / ".claude-plugin" / "plugin.json").read_text())
    return int(manifest["hooks"]["SessionStart"][0]["hooks"][0]["timeout"]) * 1000


def _install(machine: host.Machine, sandbox: list, source: str) -> dict:
    added = host.run_claude(machine, sandbox, "plugin", "marketplace", "add", source)
    installed = host.run_claude(machine, sandbox, "plugin", "install", host.PLUGIN_ID)
    return {"add": added.__dict__, "install": installed.__dict__}


def _init(machine: host.Machine, sandbox: list) -> dict:
    """The documented ``claude --init-only`` step, through the failing wrapper."""
    started = time.monotonic()
    shown = io.StringIO()
    with contextlib.redirect_stdout(shown), contextlib.redirect_stderr(shown):
        code = init_plugin.init([*sandbox, *machine.cli], host.PLUGIN_ID, machine.env)
    result = {
        "returncode": code,
        "output": shown.getvalue(),
        "seconds": round(time.monotonic() - started, 2),
    }
    if code:
        result["failure_logs"] = evidence.setup_failure_logs(
            machine.plugin_data, machine.work
        )
    return result


def _plugin_root(machine: host.Machine, sandbox: list) -> str | None:
    """Where the host runs the plugin from: the folder for a local marketplace."""
    listed = host.run_claude(machine, sandbox, "plugin", "list", "--json")
    for plugin in json.loads(listed.output or "[]"):
        if plugin.get("id") == host.PLUGIN_ID:
            return plugin.get("readFromFolder") or plugin.get("installPath")
    return None


def _stdio_in_background(machine: host.Machine, sandbox: list, root: str) -> tuple:
    """The session's own MCP server, started with the session, driven over stdio."""
    argv, env = mcp_session.server_command(Path(root), machine.plugin_data, machine.env)
    if os.name == "nt":
        executable = shutil.which(argv[0], path=env["PATH"])
        if executable is None:
            raise RuntimeError(f"Installed MCP executable not found: {argv[0]}")
        argv[0] = executable
    argv = [*sandbox, *argv]  # the stdio server too must never reach a PostgreSQL
    result: dict = {}

    def converse() -> None:
        try:
            result.update(
                mcp_session.remember_recall(
                    argv, env, machine.project, machine.server_log
                )
            )
        except Exception as exc:  # noqa: BLE001 — the report records the exact failure; the checks carry it
            result["error"] = f"{type(exc).__name__}: {exc}"

    thread = threading.Thread(target=converse, daemon=True)
    thread.start()
    return thread, result


def _session(
    machine: host.Machine, sandbox: list, name: str, root: str | None, drive: bool
) -> dict:
    """SessionStart and the MCP connect (real host) and, with ``drive``, the
    session's own server over stdio: all started at once, as a session starts."""
    started = time.monotonic()
    debug_log = machine.work / f"{name}.log"
    init_args = ("--init-only", "--debug-file", str(debug_log))
    init = host.start_claude(machine, sandbox, *init_args)
    listing = host.start_claude(machine, sandbox, "mcp", "list")
    stdio = _stdio_in_background(machine, sandbox, root) if drive and root else None
    mcp = host.finish(listing, ("mcp", "list"), started)
    init_done = host.finish(init, init_args, started)
    hook = evidence.session_start_outcome(debug_log)
    hook["system_message"] = evidence.system_message(hook.get("stdout", ""))
    server = _SERVER_LINE.search(mcp.output)
    report = {
        "init_only": init_done.__dict__,
        "mcp_list": mcp.__dict__,
        "hook": hook,
        "mcp_connected": bool(
            server
            and "Connected" in server.group(1)
            and "Failed" not in server.group(1)
        ),
    }
    if stdio is not None:
        stdio[0].join(STDIO_BOUND_SECONDS)
        report["stdio"] = (
            stdio[1] if not stdio[0].is_alive() else {"error": "no answer in time"}
        )
        report["stdio"]["seconds"] = round(time.monotonic() - started, 2)
    return report


def _supported_store(hook: dict, *, windows: bool) -> bool:
    message = hook.get("system_message", "")
    if not windows:
        return MANAGED_STORE in message
    # ADR-1114: native Windows has no pinned managed PG archive. Setup must
    # disclose that limitation, then the real SQLite store must be ready.
    return (
        message.startswith(evidence.READY + ": SQLite memory at ")
        and "SQLite fallback:" in message
        and "managed PostgreSQL unavailable here" in message
        and MANAGED_STORE not in message
    )


def _checks(report: dict, expect_semantic: bool) -> dict:
    first, second = report["session_1"], report.get("session_2", {})
    hook, hook_2 = first["hook"], second.get("hook", {})
    stdio = first.get("stdio", {})
    timeout_ms = _session_start_timeout_ms(report["plugin_root"]) or 0
    message_2 = hook_2.get("system_message", "")
    return {
        "install_exit_0": all(r["returncode"] == 0 for r in report["install"].values()),
        "hook_within_timeout": (hook.get("ms") or 10**9) < timeout_ms,
        "init_exit_0": report["init"]["returncode"] == 0,
        "hook_ready_session_1": hook.get("status") == 0 and message_starts_ready(hook),
        "supported_store_session_1": _supported_store(hook, windows=os.name == "nt"),
        "hook_installed_nothing": not any(
            "installing" in text
            for text in (hook.get("stderr", ""), hook.get("stdout", ""))
        ),
        "mcp_connected_by_host": first["mcp_connected"],
        "tools_listed": stdio.get("required_tools_present", False),
        "tools_arrived_in_session_1": stdio.get("seconds", 10**9) < STDIO_BOUND_SECONDS,
        "remember_recall": stdio.get("recall_contains_token", False),
        "no_process_left": not any(
            report.get(key, {}).get("remaining", ["not run"])
            for key in ("settle", "settle_2")
        ),
        "hook_status_0_session_2": hook_2.get("status") == 0,
        "ready_shown_session_2": message_starts_ready(hook_2),
        "semantic_outcome_session_2": (SEMANTIC_ON in message_2) == expect_semantic
        and ("failed: " in message_2 or expect_semantic),
        "no_forbidden_output": not report["forbidden"],
    }


def message_starts_ready(hook: dict) -> bool:
    return hook.get("system_message", "").startswith(evidence.READY + ":")


def _forbidden(report: dict, server_log: Path) -> list:
    texts = [r["output"] for r in report["install"].values()]
    for key in ("session_1", "session_2"):
        session = report.get(key) or {}
        texts += [session.get("mcp_list", {}).get("output", "")]
        texts += [session.get("hook", {}).get(k, "") for k in ("stdout", "stderr")]
    texts.append(server_log.read_text(errors="replace") if server_log.exists() else "")
    return evidence.forbidden_lines(*texts)


def run(args: argparse.Namespace) -> dict:
    machine = host.build_machine(Path(args.work).resolve(), args.python, args.x86_64)
    sandbox = host.sandbox_prefix(machine.work)
    report: dict = {"install": _install(machine, sandbox, args.marketplace)}
    report["init"] = _init(machine, sandbox)
    report["host_notices"] = [
        line
        for r in report["install"].values()
        for line in r["output"].splitlines()
        if _NOTICES.search(line)
    ]
    root = report["plugin_root"] = _plugin_root(machine, sandbox)
    report["session_1"] = _session(machine, sandbox, "session-1", root, drive=True)
    markers = (str(machine.work),) + ((root,) if root else ())
    report["settle"] = evidence.wait_for_no_processes(markers, args.settle_seconds)
    report["session_2"] = _session(machine, sandbox, "session-2", root, drive=False)
    # Session 2 starts its own detached workers (pipeline reanalysis):
    # "nothing left behind" covers both sessions.
    report["settle_2"] = evidence.wait_for_no_processes(markers, args.settle_seconds)
    report["spawns"] = (
        machine.spawn_log.read_text().splitlines() if machine.spawn_log.exists() else []
    )
    report["forbidden"] = _forbidden(report, machine.server_log)
    report["checks"] = _checks(report, not args.expect_semantic_failure)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--marketplace", required=True, help="checkout path or owner/repo"
    )
    parser.add_argument(
        "--work", required=True, help="new disposable directory (must not exist)"
    )
    parser.add_argument(
        "--python", default="/usr/bin/python3", help="the machine's python3"
    )
    parser.add_argument(
        "--x86_64", action="store_true", help="run plugin processes under Rosetta"
    )
    parser.add_argument("--settle-seconds", type=float, default=1200.0)
    parser.add_argument(
        "--expect-semantic-failure",
        action="store_true",
        help="the platform has no ML wheels: session 2 must name the install failure",
    )
    report = run(parser.parse_args())
    print(json.dumps(report, indent=2, default=str))
    failed = [name for name, ok in report["checks"].items() if not ok]
    print(
        f"install_e2e: {'PASS' if not failed else 'FAIL ' + ', '.join(failed)}",
        file=sys.stderr,
    )
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
