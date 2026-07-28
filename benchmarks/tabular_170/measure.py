"""Measure the tabular-encoding token delta for recall (issue #170).

The issue gates the default: on a fixed recall corpus, if the tabular encoding
cuts serialized size by >= 25% vs the current JSON encoding, ship tabular as
the default (with ``format="json"`` as the escape hatch); otherwise keep it an
opt-in ``format`` param.

Corpus (committed, reproducible): ``benchmarks/longmemeval/longmemeval_s.json``.
Its haystack turns are natural conversational text — a faithful proxy for
recall memory bodies (varied length, real prose), which is what the tabular
saving is measured against. Each simulated query returns ``MAX_RESULTS``
recall-shaped memory dicts carrying exactly the fields the recall handler
emits (id, content, score, heat, domain, tags, created_at, source). We build
the recall response envelope, then measure it two ways through the SAME code
paths the handler uses:

  (a) JSON  — ``encode_within_budget(..., "json")``: array of objects.
  (b) tabular — ``encode_within_budget(..., "tabular")``: columns-once rows.

Size is counted with ``response_budget.serialized_length`` (the exact char
count the MCP host enforces) and tokens with the host's own estimator
(chars / 4, round) — source: core/response_budget.py module docstring
(Claude Code 2.1.170 ``Xz(text) = round(len(text) / 4)``).

Output: a JSON result + MANIFEST under ``benchmarks/results/tabular-170/``.
Run: ``python3 benchmarks/tabular_170/measure.py``.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from mcp_server.core.response_budget import serialized_length
from mcp_server.core.tabular_encoding import encode_within_budget

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "benchmarks" / "longmemeval" / "longmemeval_s.json"
OUT_DIR = REPO / "benchmarks" / "results" / "tabular-170"

# Fixed corpus knobs. source: chosen to mirror the recall default
# (max_results=10, mcp_server/handlers/recall.py inputSchema) over a broad,
# deterministic query sample; N_QUERIES bounded by fixture size.
MAX_RESULTS = 10
N_QUERIES = 100

# The host's own token estimator. source: core/response_budget.py docstring
# (Claude Code 2.1.170 binary: Xz(text) = round(len(text) / 4)).
CHARS_PER_TOKEN = 4

# Char-reduction gate that flips the recall default to tabular. source: issue
# #170 as quoted in the module docstring — "if the tabular encoding cuts
# serialized size by >= 25% vs the current JSON encoding, ship tabular as the
# default".
DECISION_THRESHOLD_PCT = 25.0


def _est_tokens(chars: int) -> int:
    return round(chars / CHARS_PER_TOKEN)


def _iter_turn_contents(fixture: dict) -> list[str]:
    """Flatten every haystack turn's text into one ordered content pool."""
    contents: list[str] = []
    for question in fixture:
        for session in question.get("haystack_sessions", []):
            for turn in session:
                if isinstance(turn, dict) and turn.get("content"):
                    contents.append(turn["content"])
    return contents


def _recall_memory(mid: int, content: str) -> dict:
    """A recall-shaped memory dict — the exact field set the recall handler
    emits for a hit (mcp_server/handlers/recall.py outputSchema)."""
    return {
        "id": f"11111111-0000-0000-0000-{mid:012d}",
        "content": content,
        "score": round(0.95 - (mid % 10) * 0.01, 4),
        "heat": round(0.5 - (mid % 5) * 0.05, 4),
        "domain": "cortex",
        "tags": ["decision", "architecture"],
        "created_at": "2026-07-25T12:00:00Z",
        "source": "recall",
    }


def _recall_envelope(memories: list[dict]) -> dict:
    """The recall response envelope around a memories list (schema-aligned
    keys only — the same shape recall._handler_impl assembles)."""
    return {
        "memories": memories,
        "count": len(memories),
        "intent": "semantic",
        "low_signal_dropped": 0,
        "dispatch_tier": "pg",
    }


def measure() -> dict:
    fixture = json.loads(FIXTURE.read_text())
    pool = _iter_turn_contents(fixture)
    if len(pool) < MAX_RESULTS:
        raise SystemExit(f"corpus too small: {len(pool)} turns")

    per_query: list[dict] = []
    total_json = 0
    total_tab = 0
    cursor = 0
    for _ in range(N_QUERIES):
        window = [pool[(cursor + j) % len(pool)] for j in range(MAX_RESULTS)]
        cursor += MAX_RESULTS
        memories = [_recall_memory(i, c) for i, c in enumerate(window)]

        json_resp = encode_within_budget(_recall_envelope(memories), "memories", "json")
        tab_resp = encode_within_budget(
            _recall_envelope(memories), "memories", "tabular"
        )
        json_chars = serialized_length(json_resp)
        tab_chars = serialized_length(tab_resp)
        total_json += json_chars
        total_tab += tab_chars
        per_query.append(
            {
                "json_chars": json_chars,
                "tabular_chars": tab_chars,
                "tabular_is": tab_resp["format"],
                "reduction_pct": round(100 * (json_chars - tab_chars) / json_chars, 2),
            }
        )

    char_reduction = 100 * (total_json - total_tab) / total_json
    tok_json = _est_tokens(total_json)
    tok_tab = _est_tokens(total_tab)
    tok_reduction = 100 * (tok_json - tok_tab) / tok_json
    return {
        "corpus": "longmemeval_s.json haystack turns as recall memory bodies",
        "n_queries": N_QUERIES,
        "max_results": MAX_RESULTS,
        "fields_per_memory": len(_recall_memory(0, "x")),
        "totals": {
            "json_chars": total_json,
            "tabular_chars": total_tab,
            "char_reduction_pct": round(char_reduction, 2),
            "json_tokens_est": tok_json,
            "tabular_tokens_est": tok_tab,
            "token_reduction_pct": round(tok_reduction, 2),
        },
        "decision_threshold_pct": DECISION_THRESHOLD_PCT,
        "default": "tabular" if char_reduction >= DECISION_THRESHOLD_PCT else "json",
        "per_query_reduction_pct_min": min(q["reduction_pct"] for q in per_query),
        "per_query_reduction_pct_max": max(q["reduction_pct"] for q in per_query),
    }


def sensitivity_by_content_length() -> list[dict]:
    """Tabular reduction as a function of memory content length.

    The tabular saving is fixed field-name overhead per item; its FRACTION of
    the payload therefore falls as content grows. This sweep makes the
    crossover explicit — short (budget-truncated) memories save a lot, long
    prose memories save little — which is exactly why the natural-corpus gate
    lands where it does. Lengths span the budget-truncation regime up to full
    prose. source: budget truncation produces short content slices
    (mcp_server/core/response_budget.py water-filling); prose lengths mirror
    the fixture's own turn-length distribution (median ~376 chars).
    """
    rows: list[dict] = []
    for length in (24, 48, 96, 192, 384, 768):
        memories = [_recall_memory(i, "x" * length) for i in range(MAX_RESULTS)]
        json_chars = serialized_length(
            encode_within_budget(_recall_envelope(memories), "memories", "json")
        )
        tab_chars = serialized_length(
            encode_within_budget(_recall_envelope(memories), "memories", "tabular")
        )
        rows.append(
            {
                "content_chars": length,
                "json_chars": json_chars,
                "tabular_chars": tab_chars,
                "reduction_pct": round(100 * (json_chars - tab_chars) / json_chars, 2),
            }
        )
    return rows


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(REPO), "rev-parse", "HEAD"], text=True
        ).strip()
    except (subprocess.CalledProcessError, OSError):
        return "unknown"


def main() -> None:
    result = measure()
    result["sensitivity_by_content_length"] = sensitivity_by_content_length()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "result.json").write_text(json.dumps(result, indent=2) + "\n")

    manifest = {
        "issue": 170,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "git_commit": _git_commit(),
        "method": (
            "encode_within_budget(json) vs encode_within_budget(tabular) over "
            "recall-shaped memory dicts built from longmemeval haystack turns; "
            "size via response_budget.serialized_length; tokens via chars/4 "
            "(Claude Code host estimator)."
        ),
        "script": "benchmarks/tabular_170/measure.py",
        "script_sha256": _sha256(Path(__file__).resolve()),
        "fixture": "benchmarks/longmemeval/longmemeval_s.json",
        "fixture_sha256": _sha256(FIXTURE),
        "result": "result.json",
    }
    (OUT_DIR / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")

    t = result["totals"]
    print(f"queries={result['n_queries']} max_results={result['max_results']}")
    print(f"json_chars={t['json_chars']}  tabular_chars={t['tabular_chars']}")
    print(f"char_reduction={t['char_reduction_pct']}%")
    print(f"token_reduction={t['token_reduction_pct']}%")
    print(
        f"default -> {result['default']} "
        f"(threshold {result['decision_threshold_pct']}%)"
    )


if __name__ == "__main__":
    main()
