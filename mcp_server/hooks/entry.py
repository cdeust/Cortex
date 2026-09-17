"""Console entry point that runs a Cortex lifecycle hook from the wheel.

A Codex plugin ships only its own directory, not this repository and not
``scripts/launcher.py``. It calls the console script this module backs
(``hypermnesia-mcp-hook``, declared in ``pyproject.toml``, source: this
module's CHANGELOG entry) as
``uvx --from "hypermnesia-mcp[postgresql,sqlite]" hypermnesia-mcp-hook
<module>``. ``main()`` validates ``<module>`` against the allowlist below,
resolves the storage backend the way ``mcp_server/__main__.py`` does for
the server, wires the composition root the way ``scripts/launcher.py``
does before dispatching (issue number 560), reads the one stdin event and
normalizes it (``mcp_server.hooks.host_event``) into the Claude-shaped
event(s) the hook already reads, and dispatches to the named hook's own
``__main__`` block via ``runpy`` once per derived event (``host_dispatch``)
-- unchanged, so its headless guard and its own re-wiring still run exactly
as they do under ``scripts/launcher.py``.

No ``chdir`` (uvx does not need one), no dependency installation (uvx owns
dependencies), no capture preflight (``post_tool_capture.py`` already
applies its own skip check).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import MutableMapping

from mcp_server.hooks.host_dispatch import apply_project_root, derive_events, run_all
from mcp_server.infrastructure.backend_marker import apply_backend_resolution

# The eleven hook modules the Claude Code plugin manifest wires
# (.claude-plugin/plugin.json), verified against that file. Anything else
# is refused.
HOOK_MODULES = frozenset(
    {
        "session_start",
        "auto_recall",
        "decision_gate",
        "no_deps_gate",
        "post_tool_capture",
        "preemptive_context",
        "pipeline_impact_bump",
        "post_commit_reindex",
        "session_lifecycle",
        "compaction_checkpoint",
        "agent_briefing",
    }
)

# source: scripts/launcher.py:139 -- the same local default, PostgreSQL only.
_DEFAULT_DATABASE_URL = "postgresql://localhost:5432/cortex"


def prepare_environment(
    environ: MutableMapping[str, str], marker_path: Path | None = None
) -> None:
    """Resolve the storage backend and the PostgreSQL DATABASE_URL default.

    Precondition: ``environ`` is mutable (normally ``os.environ``).
    Postcondition: ``CORTEX_MEMORY_STORE_BACKEND`` carries whatever
    ``apply_backend_resolution`` resolves (mirrors ``mcp_server/__main__.py``
    line 22 for the server). ``DATABASE_URL`` is set to the local default
    only when it was unset AND the resolved backend is not ``sqlite``
    (mirrors ``scripts/launcher.py`` lines 135-139) -- on the SQLite backend
    the URL is unused, and injecting a PostgreSQL default would make every
    hook invocation attempt a doomed connection.
    """
    apply_backend_resolution(environ, marker_path)
    backend = environ.get("CORTEX_MEMORY_STORE_BACKEND", "")
    if "DATABASE_URL" not in environ and backend != "sqlite":
        environ["DATABASE_URL"] = _DEFAULT_DATABASE_URL


def _print_usage() -> None:
    names = ", ".join(sorted(HOOK_MODULES))
    print(
        f"Usage: hypermnesia-mcp-hook <module>\nAllowed modules: {names}",
        file=sys.stderr,
    )


def main() -> None:
    """Validate argv[1] against the allowlist, then dispatch to the hook.

    Precondition: none (argv may be missing its module argument).
    Postcondition: exits 2 with nothing on stdout when argv[1] is absent or
    not in HOOK_MODULES; otherwise wires every core/ injection seam (issue
    number 560, mirroring ``scripts/launcher.py`` lines 150-155), then runs
    ``mcp_server.hooks.<module>`` once per event derived from stdin. For a
    ``PreToolUse`` event the first non-zero exit among the derived events
    wins and stops further dispatch (an ``apply_patch`` with several file
    operations must not apply the second once the first is blocked);
    otherwise every derived event runs and the worst (highest) exit code
    among them wins, so one failing operation in a multi-event
    ``PostToolUse`` batch is never masked by a later one that succeeds.
    stdout from every run passes through untouched. ``CLAUDE_PROJECT_ROOT``
    is set from the event's ``cwd`` via ``apply_project_root`` (never
    overriding an existing value).
    """
    name = sys.argv[1] if len(sys.argv) > 1 else None
    if name not in HOOK_MODULES:
        _print_usage()
        sys.exit(2)

    prepare_environment(os.environ)

    from mcp_server.hooks.wiring import wire_composition_root  # noqa: PLC0415 - issue number 560, same seam as scripts/launcher.py:153

    wire_composition_root()

    module = f"mcp_server.hooks.{name}"
    raw = sys.stdin.read()
    payloads, hook_event_name, cwd = derive_events(module, raw)
    apply_project_root(os.environ, cwd)
    sys.exit(run_all(module, payloads, hook_event_name))


if __name__ == "__main__":
    main()
