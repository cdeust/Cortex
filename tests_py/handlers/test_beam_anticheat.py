"""Anti-cheating invariants for BEAM-10M H2H Condition C (protocol §11.1).

The whole study rests on Condition C invoking the SAME production handler
that real Cortex clients use. These tests audit the source of
``benchmarks/llm_head_to_head/cortex_caller.py`` to enforce:

  1. The only import targeting ``mcp_server.handlers.recall`` is exactly
     ``from mcp_server.handlers.recall import handler``.
  2. No call to ``setattr``, ``__class__``, ``patch``, ``monkeypatch``, or
     similar runtime mutation primitives.
  3. The kwargs passed to ``handler(...)`` are a subset of the keys
     declared in the production schema's ``inputSchema['properties']``.

Failure of any of these = a silent protocol deviation. Test failure is a
hard block on Stage 2.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from benchmarks.llm_head_to_head import cortex_caller
from mcp_server.handlers import recall as production_recall


CALLER_PATH = (
    Path(__file__).resolve().parents[2]
    / "benchmarks"
    / "llm_head_to_head"
    / "cortex_caller.py"
)


def _source() -> str:
    """Read the cortex_caller source — the audit subject."""
    return CALLER_PATH.read_text()


def _ast() -> ast.Module:
    return ast.parse(_source())


def test_only_production_handler_import():
    """Single load-bearing import: ``from mcp_server.handlers.recall import handler``.

    Any other ``mcp_server.handlers.recall`` import (e.g. importing internal
    helpers, or aliasing the module) fails the audit.
    """
    tree = _ast()
    matching: list[ast.ImportFrom] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if (node.module or "").startswith("mcp_server.handlers.recall"):
                matching.append(node)

    assert len(matching) == 1, (
        f"Expected exactly one import from mcp_server.handlers.recall, "
        f"got {len(matching)}: {[ast.unparse(m) for m in matching]}"
    )
    only = matching[0]
    assert only.module == "mcp_server.handlers.recall", (
        f"Import must target the recall module exactly, got {only.module!r}"
    )
    names = sorted(n.name for n in only.names)
    assert names == ["handler"], (
        f"Only 'handler' may be imported from production recall; got {names}"
    )
    # And no aliasing (must be `import handler`, not `import handler as foo`).
    assert all(n.asname is None for n in only.names), (
        "Aliasing the production handler is forbidden (anti-cheating §11.1)."
    )


def test_no_monkey_patching_primitives():
    """Audit for setattr / __class__ / patch / monkeypatch / mock string usage."""
    src = _source()
    forbidden = [
        "setattr(",
        "__class__ =",
        ".__class__ =",
        "monkeypatch",
        "unittest.mock",
        "from mock ",
        "import mock",
        "MagicMock",
        "patch.object",
    ]
    found = [needle for needle in forbidden if needle in src]
    assert not found, (
        f"Forbidden monkey-patch primitives in cortex_caller.py: {found}. "
        "Anti-cheating §11.1 requires the production stack to be untouched."
    )


def test_handler_kwargs_subset_of_production_schema():
    """The kwargs in handler({...}) must be a subset of the production schema."""
    tree = _ast()
    declared_props = set(
        production_recall.schema["inputSchema"]["properties"].keys()
    )

    used_keys: set[str] = set()
    for node in ast.walk(tree):
        # Look for dict literals assigned to a name then passed to handler.
        if isinstance(node, ast.Dict):
            for k in node.keys:
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    used_keys.add(k.value)

    # Filter to keys that look like the handler args dict (heuristic: only
    # consider keys that are actually production schema properties OR
    # would be off-schema). We assert ⊆.
    candidate_args = used_keys - {"results", "total"}  # the response shape
    # We only flag strings that match the handler-arg shape. Whitelist
    # known unrelated literal keys here so future legitimate dicts don't
    # create false positives.
    handler_arg_candidates = candidate_args & {
        "query",
        "domain",
        "directory",
        "max_results",
        "min_heat",
        "agent_topic",
        # if any of these slip in, they'd be off-schema and the test below
        # catches them.
        "benchmark_mode",
        "skip_rerank",
        "raw",
    }
    illegal = handler_arg_candidates - declared_props
    assert not illegal, (
        f"cortex_caller.py uses kwargs not in production schema: {illegal}. "
        f"Allowed: {sorted(declared_props)}. "
        "Anti-cheating §11.1 forbids benchmark-only kwargs."
    )


def test_cortex_recall_callable_signature_stable():
    """Smoke check that the wrapper exists and is callable.

    Defence against accidental rename/refactor that breaks the orchestrator
    while leaving the import test green.
    """
    assert callable(cortex_caller.cortex_recall)
    sig = inspect.signature(cortex_caller.cortex_recall)
    assert "question" in sig.parameters, (
        "cortex_recall must accept the BEAM question as 'question'."
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
