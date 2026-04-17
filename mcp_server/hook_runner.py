"""`cortex-hook <module>` — universal runner for Cortex hook modules.

Plugin-marketplace shim. Users install the plugin via Claude Code,
which invokes `uvx --from 'neuro-cortex-memory[postgresql]' neuro-cortex-memory`
for the MCP server. The SAME uvx cache is re-used for hook
invocations, so we need a single CLI entry point that dispatches to
any of the hook modules under ``mcp_server.hooks.*``.

Why this exists instead of ``bash + python3 + scripts/launcher.py``:

  * Marketplace users may not have Python or pip installed on the host.
    uvx (which Claude Code ships as a plugin runtime) does.
  * The bash fallback `command -v python3 || command -v python` can
    silently pick up Python 3.8 or an OS-bundled interpreter without
    the Cortex deps — tricky to diagnose. Running inside the uvx tool
    venv guarantees the exact dependency set declared in
    ``pyproject.toml[postgresql]``.
  * No shell quoting / PATH portability issues across macOS bash 3.2,
    zsh, and Windows cmd.exe / PowerShell.

Invocation from plugin.json:

    uvx --python 3.13 --from 'neuro-cortex-memory[postgresql]' \\
        cortex-hook mcp_server.hooks.session_start

The hook module's ``main()`` is called if it exists, otherwise its
``process_event()`` is invoked with JSON from stdin (compatible with
the existing Claude Code hook protocol).

Source: docs/program/phase-5-pool-admission-design.md §7 (marketplace
readiness).
"""

from __future__ import annotations

import importlib
import json
import sys


def run() -> int:
    """Entry point. Accepts the hook module name as argv[1]."""
    if len(sys.argv) < 2:
        print(
            "Usage: cortex-hook <module>\n"
            "Example: cortex-hook mcp_server.hooks.session_start",
            file=sys.stderr,
        )
        return 1

    module_name = sys.argv[1]
    # Normalize: accept either "mcp_server.hooks.X" or just "X".
    if not module_name.startswith("mcp_server.hooks."):
        module_name = f"mcp_server.hooks.{module_name}"

    try:
        mod = importlib.import_module(module_name)
    except ImportError as exc:
        print(f"[cortex-hook] module not found: {module_name} ({exc})", file=sys.stderr)
        return 2

    # Prefer main() — most hooks define it.
    if hasattr(mod, "main") and callable(mod.main):
        try:
            mod.main()
            return 0
        except SystemExit as exc:
            return int(exc.code or 0)
        except Exception as exc:
            print(f"[cortex-hook] {module_name}.main() failed: {exc}", file=sys.stderr)
            return 3

    # Fallback: hooks that expose process_event(event_dict) read JSON
    # from stdin (matches Claude Code hook protocol).
    if hasattr(mod, "process_event") and callable(mod.process_event):
        try:
            raw = sys.stdin.read().strip()
            event = json.loads(raw) if raw else {}
            mod.process_event(event)
            return 0
        except json.JSONDecodeError:
            # Empty stdin is a valid "no event" case for some hooks.
            return 0
        except Exception as exc:
            print(
                f"[cortex-hook] {module_name}.process_event() failed: {exc}",
                file=sys.stderr,
            )
            return 3

    print(
        f"[cortex-hook] {module_name} has neither main() nor process_event()",
        file=sys.stderr,
    )
    return 4


if __name__ == "__main__":
    sys.exit(run())
