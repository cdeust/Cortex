"""Raw model evidence for the auto-recall parity fixture.

This diagnostic never changes injection decisions or acceptance assertions.
It uses the same cached model and passage truncation as the injection path.
"""

from __future__ import annotations

from mcp_server.core.reranker import get_raw_ce_score


def measure_scores(corpus: list[dict], negatives: list[dict]) -> list[dict]:
    """Record every fixture pair, including positive and negative controls.

    source: hosted parity run 40690888995, hook hits 2 versus tool hits 28.
    Those hit counts alone cannot distinguish a discovery miss from a
    passage rejected by the confidence gate. Raw scores preserve that evidence.
    """
    queries = [
        {"query": case["query"], "expected": case["memory"]} for case in corpus
    ] + [{"query": row["query"], "expected": None} for row in negatives]
    report = []
    for case in queries:
        scores = []
        for passage in corpus:
            score = get_raw_ce_score(case["query"], passage["memory"])
            if score is None:
                raise RuntimeError("raw parity score inference failed")
            scores.append(
                {
                    "memory": passage["memory"],
                    "expected": passage["memory"] == case["expected"],
                    "raw_ce_score": score,
                }
            )
        report.append(
            {
                **case,
                "passages": sorted(
                    scores, key=lambda row: row["raw_ce_score"], reverse=True
                ),
            }
        )
    return report
