"""Condition C — Cortex-assembled context.

PROTOCOL §11.1 ANTI-CHEATING (load-bearing invariant for the whole study):

This module MUST invoke the production handler entry point
``mcp_server.handlers.recall.handler`` directly, with arguments that
already exist in the production schema. NO monkey-patching. NO benchmark-
only kwargs. NO ``--benchmark-mode`` flag. NO alternative code path.

The unit test ``tests_py/handlers/test_beam_anticheat.py`` reads THIS
file's source code and asserts:
  1. The only import targeting ``mcp_server.handlers.recall`` is exactly
     ``from mcp_server.handlers.recall import handler``.
  2. No call to ``setattr``, ``__class__``, or any monkey-patch primitive.
  3. The kwargs passed to ``handler({...})`` are a subset of the keys
     declared in ``recall.schema['inputSchema']['properties']``.

If you change this file, the anti-cheating test must still pass without
modification, OR a protocol addendum must be filed (§11 forbids silent
deviation).

precondition: the production memory store has been seeded with the BEAM
  conversation's memories under ``domain="beam"`` (the orchestrator does
  this via the production ``remember`` handler, not a benchmark shortcut).
postcondition: returns the same memory dicts the production handler would
  return for an interactive call with the same query — same ranking, same
  enrichments (PL/pgSQL WRRF + FlashRank + prospective + co-activation +
  rules + strategic ordering + replay tracking).
invariant: this module's import of ``handler`` is the SOLE link between
  the benchmark and the production stack. Removing this import and
  re-running condition C must produce a clean ImportError, not a silent
  fallback path.
"""

from __future__ import annotations

import asyncio
from typing import Any

# THE LOAD-BEARING IMPORT. Do not change without filing a protocol addendum.
from mcp_server.handlers.recall import handler  # noqa: E402


# Pre-registered max_results value matching condition B's k=20 (protocol §2.C
# uses the same retrieval depth as B so the comparison isolates the stack).
CORTEX_MAX_RESULTS = 20


def cortex_recall(question: str, domain: str = "beam") -> list[dict[str, Any]]:
    """Call the production recall handler — exactly as production does.

    pre: ``question`` is non-empty; ``domain`` matches what the orchestrator
      seeded via the production remember handler.
    post: returns a list of memory dicts (possibly empty) — whatever the
      production handler returned. We do NOT post-process, re-rank, or
      filter; the handler IS the production behaviour.
    """
    if not question or not question.strip():
        return []

    # The production handler is async. Run it on a fresh loop so the
    # benchmark orchestrator (synchronous) can call us. This is the same
    # pattern any synchronous caller of an MCP tool uses.
    args = {
        "query": question,
        "domain": domain,
        "max_results": CORTEX_MAX_RESULTS,
    }
    response = asyncio.run(handler(args))

    # The production handler returns {"results": [...], "total": N, ...}
    # per ``recall.py::_handler_impl``. We pull the ``results`` list and
    # return it verbatim.
    if isinstance(response, dict):
        results = response.get("results", [])
        if isinstance(results, list):
            return results
    return []


def passages_to_context(memories: list[dict[str, Any]], separator: str = "\n\n") -> str:
    """Concatenate Cortex-returned memories into the answer prompt.

    pre: memories is already ranked best-first by the production handler
      (FlashRank + strategic ordering already applied).
    post: returns a string; empty when memories is empty. The format
      preserves the production ranking — caller does NOT shuffle.
    """
    return separator.join(
        m.get("content", "") for m in memories if m.get("content")
    )
