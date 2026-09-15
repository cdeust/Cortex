"""Static entry-point enumeration (issue #560 review, 2026-09-16): every
real process entry point that can reach a core/ injection seam must call
mcp_server.hooks.wiring.wire_composition_root(). Enumerated
mechanically -- reading .claude-plugin/plugin.json's hook commands and
scanning scripts/benchmarks for imports of mcp_server.core/handlers --
instead of a hand-maintained list, so a new entry point added later
without wiring fails this test immediately rather than only failing at
runtime in production (the exact class of bug this review round found in
mcp_server/hooks/consolidate_background.py).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
# An actual call, not a mention in a comment or docstring.
_WIRE_CALL_RE = re.compile(r"^\s*(?:\w+\.)?wire_composition_root\(\)", re.MULTILINE)
_CORE_IMPORT_RE = re.compile(
    r"^\s*(?:from|import)\s+mcp_server\.(?:core|handlers)\b", re.MULTILINE
)
# A real top-level main block, not the phrase quoted in a docstring.
_MAIN_BLOCK_RE = re.compile(r'^if __name__ == "__main__":', re.MULTILINE)
_HOOK_MODULE_RE = re.compile(r"mcp_server\.hooks\.([A-Za-z_][\w]*)")


def _calls_wire(path: Path) -> bool:
    text = path.read_text(encoding="utf-8", errors="ignore")
    return bool(_WIRE_CALL_RE.search(text))


def _reaches_core(path: Path) -> bool:
    text = path.read_text(encoding="utf-8", errors="ignore")
    return bool(_CORE_IMPORT_RE.search(text))


def _hook_module_names() -> set[str]:
    """Every ``mcp_server.hooks.<name>`` module referenced as a hook
    command anywhere in .claude-plugin/plugin.json."""
    plugin_json = json.loads(
        (REPO_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8")
    )
    names: set[str] = set()

    def walk(node: object) -> None:
        if isinstance(node, str):
            names.update(_HOOK_MODULE_RE.findall(node))
        elif isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(plugin_json)
    return names


def test_every_plugin_hook_command_wires_the_composition_root():
    names = _hook_module_names()
    assert names, ".claude-plugin/plugin.json enumeration found no hooks -- broken test"
    missing = [
        name
        for name in sorted(names)
        if (REPO_ROOT / "mcp_server" / "hooks" / f"{name}.py").is_file()
        and not _calls_wire(REPO_ROOT / "mcp_server" / "hooks" / f"{name}.py")
    ]
    assert not missing, f"hook entry points missing wire_composition_root(): {missing}"


def test_every_hook_with_a_main_block_wires_the_composition_root():
    """.claude-plugin/plugin.json only lists hooks Claude Code invokes
    directly; some (consolidate_background, ingest_codebase_background,
    capture_worker) are spawned dynamically by another hook's own
    subprocess.Popen call and never appear there -- this is exactly the
    entry point the 2026-09-16 review found unwired. Every ``mcp_server/
    hooks/*.py`` with its own ``if __name__ == "__main__":`` block is a
    real process entry point regardless of how it gets invoked."""
    hook_files = sorted((REPO_ROOT / "mcp_server" / "hooks").glob("*.py"))
    entry_points = [
        p for p in hook_files if _MAIN_BLOCK_RE.search(p.read_text(encoding="utf-8"))
    ]
    assert entry_points, "no hooks/*.py have a __main__ block -- broken test"
    missing = [p for p in entry_points if not _calls_wire(p)]
    assert not missing, f"hook entry points missing wire_composition_root(): {missing}"


def test_main_wires_the_composition_root():
    assert _calls_wire(REPO_ROOT / "mcp_server" / "__main__.py")


def test_launcher_wires_the_composition_root():
    assert _calls_wire(REPO_ROOT / "scripts" / "launcher.py")


def test_every_script_reaching_core_wires_the_composition_root():
    scripts = sorted((REPO_ROOT / "scripts").glob("*.py"))
    reaching = [p for p in scripts if _reaches_core(p)]
    assert reaching, "no scripts/*.py import mcp_server.core/handlers -- broken test"
    missing = [p for p in reaching if not _calls_wire(p)]
    assert not missing, f"scripts missing wire_composition_root(): {missing}"


def test_every_benchmark_run_script_reaching_core_wires_the_composition_root():
    """No benchmarks/**/run_*.py imports mcp_server.core/handlers on this
    (wiki-only) branch, so this enumerates an empty set today; once
    issue #568's benchmark bootstrap ports onto
    mcp_server.hooks.wiring, any run_*.py it wires will satisfy this
    the same way (directly or by importing that bootstrap)."""
    run_scripts = sorted((REPO_ROOT / "benchmarks").glob("**/run_*.py"))
    reaching = [p for p in run_scripts if _reaches_core(p)]
    missing = []
    for p in reaching:
        text = p.read_text(encoding="utf-8", errors="ignore")
        if not (_calls_wire(p) or "_composition_root_wiring" in text):
            missing.append(p)
    assert not missing, f"benchmark scripts missing composition-root wiring: {missing}"
