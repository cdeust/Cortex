"""Execute real handler/recall function bodies with fake IO and neural stages.

This contract probe reports cardinalities, never latency or model quality.
It stops at the handler's pre-enrichment cap. Exact-ID dispatch uses the
production helper; the ordinary fixture performs no I/O.
"""

from __future__ import annotations

import ast
import asyncio
import json
from pathlib import Path
import re
from types import SimpleNamespace

from benchmarks.reranker_matrix.runtime import fetched
from mcp_server.handlers.decision_recall import exact_lookup


class ProbeFinishedError(Exception):
    """The observed handler boundary has been reached."""


def source_function(relative: str, name: str, namespace: dict):
    path = Path(__file__).resolve().parents[2] / relative
    tree = ast.parse(path.read_text())
    node = next(
        n
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name
    )
    future = ast.ImportFrom(
        module="__future__", names=[ast.alias(name="annotations")], level=0
    )
    module = ast.fix_missing_locations(ast.Module(body=[future, node], type_ignores=[]))
    exec(compile(module, str(path), "exec"), namespace)  # noqa: S102 — source: ADR-0862
    return namespace[name]


def sql_multiplier() -> int:
    path = (
        Path(__file__).resolve().parents[2] / "mcp_server/infrastructure/pg_schema.py"
    )
    tree = ast.parse(path.read_text())
    node = next(
        n
        for n in tree.body
        if isinstance(n, ast.Assign)
        and any(
            isinstance(t, ast.Name) and t.id == "RECALL_MEMORIES_LAZY_FN"
            for t in n.targets
        )
    )
    sql = ast.literal_eval(node.value)
    match = re.search(r"LIMIT p_max_results \* (\d+);", sql)
    if match is None:
        raise ValueError("cannot prove current SQL output multiplier")
    return int(match[1])


def store_reply(observations: dict):
    def reply(**kwargs):
        observations["sql_max_results"] = kwargs["max_results"]
        count = kwargs["max_results"] * sql_multiplier()
        observations["sql_returned"] = count
        return [{"memory_id": i, "content": "fixture"} for i in range(count)]

    return reply


def fetch_stage(multiplier: int, observations: dict):
    # untrusted_origin_factor: renamed from the UNTRUSTED_ORIGIN_FACTOR
    # module constant to a function, issue #560 (core/ may not import os).
    ns = {
        "trusted_origins_at_read": lambda: (),
        "untrusted_origin_factor": lambda: 1.0,
    }
    original = source_function(
        "mcp_server/core/pg_recall_context.py", "_wrrf_fetch", ns
    )
    ns.update(
        {
            "classify_query_intent": lambda query: {"intent": "general"},
            "compute_pg_weights": lambda *args: {},
            "replace": lambda ctx, **kw: SimpleNamespace(**(vars(ctx) | kw)),
            "familiarity_triage": lambda rows, *args, **kw: SimpleNamespace(
                candidates=rows, shortcut=False
            ),
            "_wrrf_fetch": fetched(original, multiplier, observations["fetches"]),
        }
    )
    source_function(
        "mcp_server/core/pg_recall_context.py", "_observe_candidate_embeddings", ns
    )
    return source_function(
        "mcp_server/core/pg_recall_context.py", "fetch_and_triage", ns
    )


def pipeline(multiplier: int, observations: dict):
    def rerank(rows, ctx):
        observations["rerank_candidates"] = len(rows)
        return rows

    ns = {
        "set_retrieval_tier": lambda tier: None,
        "fetch_and_triage": fetch_stage(multiplier, observations),
        "apply_rerank_nudges": rerank,
    }
    for name in (
        "apply_recollection_pipeline",
        "reserve_typed_pool",
        "apply_final_stages",
    ):
        ns[name] = lambda rows, ctx: rows
    return source_function(
        "mcp_server/core/pg_recall_stages.py", "run_recall_pipeline", ns
    )


def handler_globals(multiplier: int, observations: dict) -> dict:
    def filtered(rows):
        observations["handler_before_filter"] = len(rows)
        # Fixture: every second returned row is low-signal. No production rule changed.
        kept = rows[::2]
        observations["handler_after_filter"] = len(kept)
        return kept, len(rows) - len(kept)

    def finish(rows, *args, **kwargs):
        observations["pre_enrichment_count"] = len(rows)
        raise ProbeFinishedError

    recall = source_function(
        "mcp_server/core/pg_recall.py",
        "recall",
        {
            "RecallContext": lambda **fields: SimpleNamespace(
                candidate_embeddings=None, **fields
            ),
            "run_recall_pipeline": pipeline(multiplier, observations),
        },
    )
    return {
        "exact_lookup": exact_lookup,
        "parse_format": lambda fmt: fmt,
        "root_agent_topic": lambda: None,
        "get_memory_settings": lambda: SimpleNamespace(WRRF_K=60),
        "_get_store": lambda: SimpleNamespace(
            recall_memories=store_reply(observations)
        ),
        "get_embedding_engine": lambda: SimpleNamespace(encode=lambda text: None),
        "_momentum_state": {},
        "pg_recall": recall,
        "filter_low_signal": filtered,
        "inject_triggered_memories": finish,
    }


def probe(multiplier: int, max_results: int, include_low_signal: bool) -> dict:
    observations = {
        "max_results": max_results,
        "multiplier": multiplier,
        "include_low_signal": include_low_signal,
        "fetches": [],
    }
    handler = source_function(
        "mcp_server/handlers/recall.py",
        "_handler_impl",
        handler_globals(multiplier, observations),
    )
    try:
        asyncio.run(
            handler(
                {
                    "query": "fixture",
                    "max_results": max_results,
                    "include_low_signal": include_low_signal,
                }
            )
        )
    except ProbeFinishedError:
        return observations
    raise RuntimeError("handler did not reach the observed boundary")


def main() -> None:
    # source: ADR-0862
    print(
        json.dumps(
            [probe(m, 10, include) for m in (2, 3) for include in (False, True)],
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
