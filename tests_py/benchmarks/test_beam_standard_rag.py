"""Condition B isolation invariant — vanilla Lewis-2020 RAG only.

Protocol §2.B and §11.1 require Condition B to use a SEPARATE code path
from production recall. This test reads the source of
``retriever_baselines.py`` and asserts:

  1. NO import from ``mcp_server.handlers.recall`` (that's Condition C).
  2. NO import from ``mcp_server.core.pg_recall`` (PL/pgSQL fusion is the
     Cortex stack).
  3. NO import from ``mcp_server.core.reranker`` (FlashRank is the Cortex
     stack).
  4. NO call to functions named ``recall_memories``, ``apply_rules``,
     ``inject_triggered_memories``, ``apply_strategic_ordering``, or
     anything else that smells like the production stack.

Failure here means Condition B has been silently merged into Condition C
and the C-vs-B comparison is no longer measuring the Cortex stack.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from benchmarks.llm_head_to_head import retriever_baselines


SOURCE_PATH = Path(retriever_baselines.__file__)


def _source() -> str:
    return SOURCE_PATH.read_text()


def test_no_recall_handler_import():
    """Condition B must NOT import production recall (that's C's job)."""
    src = _source()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert not module.startswith("mcp_server.handlers.recall"), (
                f"retriever_baselines.py imports {module} — anti-cheating §11.1 "
                "forbids Condition B from touching the production handler."
            )


def test_no_pg_recall_import():
    """No PL/pgSQL fusion path (that's the Cortex stack)."""
    src = _source()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert "pg_recall" not in module, (
                f"retriever_baselines.py imports {module} — that's the Cortex "
                "fusion path, not vanilla RAG."
            )


def test_no_reranker_import():
    """FlashRank is part of the Cortex stack — must not appear in B."""
    src = _source()
    forbidden_modules = (
        "mcp_server.core.reranker",
        "mcp_server.core.scoring",
        "mcp_server.core.spreading_activation",
        "mcp_server.core.spreading",
        "mcp_server.core.thermodynamics",
        "mcp_server.core.memory_rules",
    )
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for forbidden in forbidden_modules:
                assert not module.startswith(forbidden), (
                    f"retriever_baselines.py imports {module}, which is part "
                    f"of the Cortex stack (matches forbidden prefix {forbidden!r})."
                )


def test_no_cortex_stack_function_calls():
    """No AST-level call to production-stack function names.

    Audits ``ast.Call`` nodes only — docstrings/comments mentioning these
    names (legitimate: the module's contract DOCUMENTS what it doesn't do)
    are not flagged.
    """
    tree = ast.parse(_source())
    forbidden_call_names = {
        "recall_memories",
        "apply_rules",
        "inject_triggered_memories",
        "apply_strategic_ordering",
        "pg_recall",
        "flashrank_rerank",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name: str | None = None
            if isinstance(fn, ast.Name):
                name = fn.id
            elif isinstance(fn, ast.Attribute):
                name = fn.attr
            if name and name in forbidden_call_names:
                raise AssertionError(
                    f"retriever_baselines.py invokes forbidden Cortex-stack "
                    f"function {name!r}; Condition B must remain vanilla RAG."
                )


def test_uses_only_minilm_embedding():
    """The single allowed shared component is the MiniLM embedding engine."""
    src = _source()
    tree = ast.parse(src)
    has_embedding_import = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == "mcp_server.infrastructure.embedding_engine":
                has_embedding_import = True
    assert has_embedding_import, (
        "retriever_baselines.py must import the shared embedding engine "
        "(MiniLM) — protocol §2.B isolates retrieval-stack effects from "
        "embedding-choice effects."
    )


def test_query_uses_cosine_only():
    """The SQL query references the embedding cosine operator and nothing else.

    This catches accidental joins to ``heat``, ``access_count``, or other
    Cortex-internal columns that would change B's behaviour.
    """
    src = _source()
    # The single allowed query is in standard_rag(); verify its body.
    # We look for the SQL string content.
    sql_match = re.search(r"sql\s*=\s*\((.*?)\)", src, re.DOTALL)
    assert sql_match, "Could not locate the standard_rag SQL string."
    sql_text = sql_match.group(1).lower()

    # Must reference embedding / cosine.
    assert "embedding" in sql_text
    assert "<=>" in sql_text  # pgvector cosine distance operator

    # Must NOT reference Cortex-stack columns.
    forbidden_cols = ["heat", "access_count", "replay_count", "consolidation_stage"]
    for col in forbidden_cols:
        assert col not in sql_text, (
            f"Standard RAG SQL references {col!r} — that's the Cortex stack."
        )
