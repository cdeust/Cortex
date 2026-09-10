"""Local size observations and externally supplied Claude token counts.

No tokenizer, API client or model import. Counts must identify the exact
captured SDK response, model and measurement source; local heuristics are never
accepted as provider-observed input_tokens. This module recommends no budget or share.
"""

from __future__ import annotations

import hashlib
import json
import statistics
from pathlib import Path


def content_digest(content: list[dict]) -> str:
    data = json.dumps(content, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def text_observation(content: list[dict]) -> dict:
    if any(block.get("type") != "text" for block in content):
        raise ValueError("This calibration only supports MCP text content")
    texts = [block["text"] for block in content]
    # source: ADR-0781
    units = [
        len(text.encode("utf-16-le", errors="surrogatepass")) // 2 for text in texts
    ]
    return {
        "content_sha256": content_digest(content),
        "text_code_points": sum(map(len, texts)),
        "text_utf8_bytes": sum(len(text.encode("utf-8")) for text in texts),
        "text_utf16_units": sum(units),
        # source: ADR-0781
        "host_estimated_tokens": sum((length + 2) // 4 for length in units),
    }


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def token_observations(records: list[dict]) -> dict[str, dict]:
    indexed = {}
    for record in records:
        count = record.get("input_tokens")
        if type(count) is not int or count <= 0:
            raise ValueError("Observed input_tokens must be a positive integer")
        if record.get("method") != "messages.countTokens":
            raise ValueError(
                "An API count observation is required, not a local heuristic"
            )
        if not record.get("model") or not record.get("source"):
            raise ValueError("Token evidence requires model and source")
        key = record["content_sha256"]
        if key in indexed:
            raise ValueError("Duplicate token evidence for a content digest")
        indexed[key] = record
    if len({record["model"] for record in indexed.values()}) > 1:
        raise ValueError("Do not pool token ratios from different models")
    return indexed


def _ratios(observations: list[dict], counts: dict[str, dict]) -> dict:
    if not counts:
        return {"status": "pending provider token observations"}
    keys = {row["content_sha256"] for row in observations}
    if keys != set(counts):
        raise ValueError(
            "Token evidence must cover exactly the captured content digests"
        )
    ratios = [
        row["text_utf16_units"] / counts[row["content_sha256"]]["input_tokens"]
        for row in observations
    ]
    return {
        "status": "external API observations supplied; not independently authenticated",
        "utf16_units_per_input_token": {
            "min": min(ratios),
            "median": statistics.median(ratios),
            "max": max(ratios),
        },
        "models": sorted({row["model"] for row in counts.values()}),
        "max_input_tokens": max(row["input_tokens"] for row in counts.values()),
        "provider_observations": [counts[key] for key in sorted(counts)],
        "budget_recommendation": None,
        "item_share_recommendation": None,
    }


def summarize(records: list[dict], counts: dict[str, dict]) -> dict:
    observations = [text_observation(record["result"]["content"]) for record in records]
    return {
        "responses": len(records),
        "distinct_requests": len({record["request_sha256"] for record in records}),
        "distinct_contents": len({row["content_sha256"] for row in observations}),
        "tools": sorted({record["tool"] for record in records}),
        "observations": observations,
        "token_calibration": _ratios(observations, counts),
    }
