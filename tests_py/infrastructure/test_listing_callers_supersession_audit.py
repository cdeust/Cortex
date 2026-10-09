"""Only a maintenance caller may ask a shared listing for the physical chain.

The listing primitives return supersession chain heads by default. A caller
that passes ``heads_only=False`` receives retracted rows, so each such call
site must be a reviewed maintenance site, named here. A new content-serving
caller cannot slip one in without this test failing.
"""

from __future__ import annotations

import ast
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2] / "mcp_server"
_LISTINGS = frozenset(
    {
        "get_memories_for_domain",
        "get_memories_for_directory",
        "get_hot_memories",
        "get_memories_mentioning_entity",
        "get_recently_accessed_memories",
    }
)
# source: reviewed 2026-10-10 -- validation re-grades the physical chain;
# pruning and plasticity are consolidation passes over the physical rows.
_MAINTENANCE_SITES = frozenset(
    {
        "handlers/validate_memory.py",
        "handlers/consolidation/pruning.py",
        "handlers/consolidation/plasticity.py",
    }
)


def _physical_chain_calls() -> set[str]:
    sites: set[str] = set()
    for path in _ROOT.rglob("*.py"):
        rel = path.relative_to(_ROOT).as_posix()
        if rel.startswith("infrastructure/"):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _LISTINGS
            ):
                continue
            for kw in node.keywords:
                if (
                    kw.arg == "heads_only"
                    and isinstance(kw.value, ast.Constant)
                    and kw.value.value is False
                ):
                    sites.add(rel)
    return sites


def test_only_reviewed_maintenance_sites_request_the_physical_chain():
    assert _physical_chain_calls() == _MAINTENANCE_SITES
