#!/usr/bin/env python3
"""Zero-ops install check: the owner's three commands on a clean machine.

    claude plugin marketplace add <checkout | cdeust/Cortex>
    claude plugin install hypermnesia-mcp@cortex-plugins
    first session -> "Cortex ready", tools answer, remember -> recall works

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

source: docs/adr/ADR-1104-zero-ops-plugin-install.md
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evidence  # noqa: E402
import host  # noqa: E402
import mcp_session  # noqa: E402

SESSION_START_TIMEOUT_MS = 30_000  # source: .claude-plugin/plugin.json SessionStart "timeout": 30
_SERVER_LINE = re.compile(r"plugin:hypermnesia-mcp:cortex: \S+ (\S+)/scripts/launcher\.py mcp_server - (.*)")
_PROMPTS = re.compile(r"not yet set|/plugin configure|--config", re.IGNORECASE)


def _install(machine: host.Machine, sandbox: list, source: str) -> dict:
    added = host.run_claude(machine, sandbox, "plugin", "marketplace", "add", source)
    installed = host.run_claude(machine, sandbox, "plugin", "install", host.PLUGIN_ID)
    return {"add": added.__dict__, "install": installed.__dict__}


def _first_session(machine: host.Machine, sandbox: list, debug_log: Path) -> dict:
    """SessionStart (real host) and the MCP connect (real host), concurrently."""
    started = time.monotonic()
    init_args = ("--init-only", "--debug-file", str(debug_log))
    init = host.start_claude(machine, sandbox, *init_args)
    listing = host.start_claude(machine, sandbox, "mcp", "list")
    mcp = host.finish(listing, ("mcp", "list"), started)
    init_done = host.finish(init, init_args, started)
    hook = evidence.session_start_outcome(debug_log)
    hook["system_message"] = evidence.system_message(hook.get("stdout", ""))
    server = _SERVER_LINE.search(mcp.output)
    return {
        "init_only": init_done.__dict__,
        "mcp_list": mcp.__dict__,
        "hook": hook,
        "plugin_root": server.group(1) if server else None,
        "mcp_connected": bool(server and "Connected" in server.group(2) and "Failed" not in server.group(2)),
    }


def _checks(report: dict) -> dict:
    first, second = report["session_1"], report.get("session_2", {})
    hook = first["hook"]
    stdio = report.get("stdio", {})
    return {
        "install_exit_0": all(r["returncode"] == 0 for r in report["install"].values()),
        "nothing_prompts": not report["prompts"],
        "hook_status_0": hook.get("status") == 0,
        "hook_within_timeout": (hook.get("ms") or 10**9) < SESSION_START_TIMEOUT_MS,
        "ready_shown_session_1": evidence.READY in hook.get("system_message", ""),
        "mcp_connected_by_host": first["mcp_connected"],
        "tools_listed": stdio.get("required_tools_present", False),
        "remember_recall": stdio.get("recall_contains_token", False),
        "no_process_left": not report.get("settle", {}).get("remaining", ["not run"]),
        "ready_shown_session_2": evidence.READY in second.get("hook", {}).get("system_message", ""),
        "no_forbidden_output": not report["forbidden"],
    }


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
    report["prompts"] = [
        line for r in report["install"].values() for line in r["output"].splitlines() if _PROMPTS.search(line)
    ]
    report["session_1"] = _first_session(machine, sandbox, machine.work / "session-1.log")
    server_log = machine.work / "mcp-server.stderr"
    root = report["session_1"]["plugin_root"]
    if root:
        argv, env = mcp_session.server_command(Path(root), machine.plugin_data, machine.env)
        argv = [*sandbox, *argv]  # the stdio server too must never reach a PostgreSQL
        try:
            report["stdio"] = mcp_session.remember_recall(argv, env, machine.project, server_log)
        except Exception as exc:  # noqa: BLE001 — the report records the exact failure; the checks carry it
            report["stdio"] = {"error": f"{type(exc).__name__}: {exc}"}
    markers = (str(machine.work),) + ((root,) if root else ())
    report["settle"] = evidence.wait_for_no_processes(markers, args.settle_seconds)
    report["session_2"] = _first_session(machine, sandbox, machine.work / "session-2.log")
    report["spawns"] = machine.spawn_log.read_text().splitlines() if machine.spawn_log.exists() else []
    report["forbidden"] = _forbidden(report, server_log)
    report["checks"] = _checks(report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--marketplace", required=True, help="checkout path or owner/repo")
    parser.add_argument("--work", required=True, help="scratch directory (recreated)")
    parser.add_argument("--python", default="/usr/bin/python3", help="the machine's python3")
    parser.add_argument("--x86_64", action="store_true", help="run plugin processes under Rosetta")
    parser.add_argument("--settle-seconds", type=float, default=1200.0)
    report = run(parser.parse_args())
    print(json.dumps(report, indent=2, default=str))
    failed = [name for name, ok in report["checks"].items() if not ok]
    print(f"install_e2e: {'PASS' if not failed else 'FAIL ' + ', '.join(failed)}", file=sys.stderr)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
