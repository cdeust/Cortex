"""Rebuild, offline, the recall payload a benchmark query would have returned.

The per-query journal (``benchmarks/lib/query_log.py``) keeps what each query
retrieved. This module renders those items through the same pure functions
the ``recall`` handler uses (``bound_payload`` with the ``memories`` list
target, ``reserved_budget``, ``encode_within_budget``) in both the ``json``
and ``tabular`` formats, so its size can be counted in model tokens.

It is a **bench-equivalent payload**, not the live handler's output: the
benchmark calls ``pg_recall`` directly, so the handler's 3x over-fetch,
low-signal filter, triggered-memory injection, co-activation and rules stages
never ran, and the payload carries only the fields the journal kept
(``memory_id``, ``content``, ``score``) plus ``count``.

source: Cortex benchmark refresh plan, step 1 (2026-09-30), item (f);
mcp_server/handlers/recall.py (payload assembly after ``annotate_source_attribution``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp_server.core.response_budget import (
    MAX_RESPONSE_CHARS,
    ListTarget,
    bound_payload,
)
from mcp_server.core.tabular_encoding import (
    FORMAT_JSON,
    FORMAT_TABULAR,
    encode_within_budget,
    reserved_budget,
)

FORMATS = (FORMAT_JSON, FORMAT_TABULAR)


class MissingContentError(ValueError):
    """The journal was written without ``--query-log-content``."""


def load_queries(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def item_texts(query: dict[str, Any]) -> list[str]:
    """The retrieved texts of one journalled query, in rank order."""
    texts = []
    for item in query["items"]:
        if "content" not in item:
            raise MissingContentError(
                f"query {query['question_id']} has no item content; rerun the "
                "benchmark with --query-log-content"
            )
        texts.append(item["content"])
    return texts


def render_payload(query: dict[str, Any], fmt: str) -> str:
    """Serialized bench-equivalent recall response for ``query`` in ``fmt``."""
    memories = [
        {"memory_id": i.get("memory_id"), "content": text, "score": i.get("score")}
        for i, text in zip(query["items"], item_texts(query), strict=True)
    ]
    resp: dict[str, Any] = {"memories": memories, "count": len(memories)}
    resp = bound_payload(
        resp,
        [ListTarget("memories", weight_key="score")],
        reserved_budget(MAX_RESPONSE_CHARS),
    )
    resp["count"] = len(resp["memories"])
    resp = encode_within_budget(resp, "memories", fmt, MAX_RESPONSE_CHARS)
    return json.dumps(resp, separators=(",", ":"), ensure_ascii=False, default=str)
