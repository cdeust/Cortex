"""Count, offline, the model tokens a benchmark's retrieval put in context.

Reads a ``<stem>.queries.jsonl`` journal written with ``--query-log-content``
and, for each query, counts with Anthropic's token-counting endpoint
(``client.messages.count_tokens``, the Messages API ``count_tokens`` route):

- ``t_retrieved``: the retrieved texts, summed item by item;
- ``t_response_json`` / ``t_response_tabular``: the bench-equivalent recall
  payload (``benchmarks/tokens/payload.py``) in each format;
- with ``--lme-dataset``, ``t_full_history``: the question's whole haystack,
  its sessions rendered as the runner renders them and joined by blank lines.

This step is separate from scoring and never runs inside a benchmark leg: it
needs the network and an Anthropic credential, resolved by the SDK from the
environment or an ``ant auth login`` profile, never stored in the repository.
Run it with the SDK added for this invocation only::

    uv run --extra benchmarks --with anthropic \\
        python benchmarks/tokens/count_tokens.py \\
        --queries RESULTS_DIR/locomo.queries.jsonl \\
        --out RESULTS_DIR/locomo.tokens.json

Each count is ``input_tokens`` of a one-message request minus the envelope:
the count of the message ``"x"`` minus one, which assumes a single ASCII
letter is one token. The envelope and the model id are written into the
output so the subtraction can be redone.

source: Cortex benchmark refresh plan, step 1 (2026-09-30), item (f);
Anthropic token-counting reference (count_tokens, never tiktoken, which
undercounts Claude text).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Protocol

REPO = Path(__file__).resolve().parent.parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from benchmarks.tokens.payload import (  # noqa: E402
    FORMATS,
    item_texts,
    load_queries,
    render_payload,
)

DEFAULT_MODEL = "claude-opus-5"
ENVELOPE_PROBE = "x"


class CountingClient(Protocol):
    """The slice of ``anthropic.Anthropic`` this script uses."""

    @property
    def messages(self) -> Any: ...


class TokenCounter:
    """Counts text tokens for one pinned model, envelope removed, cached by sha256."""

    def __init__(self, client: CountingClient, model: str) -> None:
        self.client = client
        self.model = model
        self._cache: dict[str, int] = {}
        self.envelope = self._raw(ENVELOPE_PROBE) - 1

    def _raw(self, text: str) -> int:
        reply = self.client.messages.count_tokens(
            model=self.model, messages=[{"role": "user", "content": text}]
        )
        return int(reply.input_tokens)

    def count(self, text: str) -> int:
        if not text:
            return 0
        key = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if key not in self._cache:
            self._cache[key] = self._raw(text) - self.envelope
        return self._cache[key]


def query_row(counter: TokenCounter, query: dict[str, Any]) -> dict[str, Any]:
    """Token counts for one journalled query."""
    row: dict[str, Any] = {
        "question_id": query["question_id"],
        "retrieved_items": len(query["items"]),
        "retrieved_bytes": query.get("retrieved_bytes"),
        "t_retrieved": sum(counter.count(text) for text in item_texts(query)),
    }
    for fmt in FORMATS:
        row[f"t_response_{fmt}"] = counter.count(render_payload(query, fmt))
    return row


def full_history_texts(dataset_path: Path) -> dict[str, str]:
    """Each LongMemEval question's whole haystack, as the runner renders it."""
    from benchmarks.longmemeval.run_benchmark import (  # noqa: PLC0415
        session_to_memory_content,
    )

    records = json.loads(dataset_path.read_text(encoding="utf-8"))
    return {
        str(r["question_id"]): "\n\n".join(
            session_to_memory_content(session, sid)[0]
            for session, sid in zip(
                r["haystack_sessions"], r["haystack_session_ids"], strict=True
            )
        )
        for r in records
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Mean, median and 95th percentile of every ``t_*`` column."""
    keys = sorted({k for row in rows for k in row if k.startswith("t_")})
    summary = {}
    for key in keys:
        values = [row[key] for row in rows if row.get(key) is not None]
        if not values:
            continue
        summary[key] = {
            "n": len(values),
            "mean": statistics.fmean(values),
            "median": statistics.median(values),
            "p95": statistics.quantiles(values, n=20)[-1]
            if len(values) > 1
            else values[0],
        }
    return summary


def count_journal(
    counter: TokenCounter, queries: list[dict[str, Any]], histories: dict[str, str]
) -> dict[str, Any]:
    rows = []
    for query in queries:
        row = query_row(counter, query)
        history = histories.get(str(query["question_id"]))
        if history is not None:
            row["t_full_history"] = counter.count(history)
            row["retrieved_over_full_history"] = (
                row["t_retrieved"] / row["t_full_history"]
                if row["t_full_history"]
                else None
            )
        rows.append(row)
    return {
        "model": counter.model,
        "envelope_tokens": counter.envelope,
        "envelope_assumption": "count('x') - 1: a single ASCII letter is one token",
        "payload_note": "bench-equivalent payload; see benchmarks/tokens/payload.py",
        "summary": summarize(rows),
        "rows": rows,
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--lme-dataset", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, client: CountingClient | None = None) -> None:
    args = _parse_args(argv)
    if client is None:
        import anthropic  # noqa: PLC0415 — optional; see the module docstring

        client = anthropic.Anthropic()
    queries = load_queries(args.queries)
    if args.limit > 0:
        queries = queries[: args.limit]
    histories = full_history_texts(args.lme_dataset) if args.lme_dataset else {}
    report = count_journal(TokenCounter(client, args.model), queries, histories)
    report["queries_file"] = str(args.queries)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
