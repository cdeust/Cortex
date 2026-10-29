"""Raw model evidence for the auto-recall parity fixture.

This diagnostic never changes injection decisions or acceptance assertions.
It uses the same cached model and passage truncation as the injection path.
"""

from __future__ import annotations

from mcp_server.core.hopfield import cosine_similarity
from mcp_server.core.reranker import get_raw_ce_score
from mcp_server.infrastructure.embedding_engine import get_embedding_engine


def _neural_vector(text: str) -> bytes:
    """Use the preflighted tool encoder; refuse missing or fallback vectors."""
    engine = get_embedding_engine()
    vector = engine.encode(text)
    if vector is None or engine.mode != "neural":
        raise RuntimeError("parity score measurement requires neural embeddings")
    return vector


# source: ONNX vs sentence-transformers on this fixture measured 0.99999997
# (2026-10-29); below this the hook's query space is not the stored space.
_MIN_ENCODER_AGREEMENT = 0.999


def query_encoder_agreement(corpus: list[dict]) -> dict | None:
    """The hook's torch-free encoder must reproduce the stored vectors.

    Returns None for prior source, which has no hook query encoder.
    """
    try:
        from mcp_server.infrastructure.hook_query_encoder import (  # noqa: PLC0415 -- absent from prior source
            cached_query_encoder,
        )
    except ImportError:
        return None
    encoder = cached_query_encoder()
    if encoder is None:
        raise RuntimeError("hook query encoder absent after preflight")
    texts = [case["memory"] for case in corpus] + [case["query"] for case in corpus]
    worst = min(
        cosine_similarity(encoder(text).tobytes(), _neural_vector(text))
        for text in texts
    )
    if worst < _MIN_ENCODER_AGREEMENT:
        raise RuntimeError(f"hook query encoder disagrees with engine: {worst}")
    return {"min_cosine_to_engine": worst}


def _score_query(case: dict, corpus: list[dict], vectors: dict) -> dict:
    """Score one query against every fixture passage, CE order first."""
    query_vector = _neural_vector(case["query"])
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
                "embedding_cosine": cosine_similarity(
                    query_vector, vectors[passage["memory"]]
                ),
            }
        )
    embedding_order = sorted(
        scores, key=lambda row: row["embedding_cosine"], reverse=True
    )
    for rank, passage in enumerate(embedding_order, start=1):
        passage["embedding_rank"] = rank
    return {
        **case,
        "passages": sorted(scores, key=lambda row: row["raw_ce_score"], reverse=True),
    }


def measure_scores(corpus: list[dict], negatives: list[dict]) -> list[dict]:
    """Record every fixture pair, including positive and negative controls.

    source: hosted parity run 40690888995, hook hits 2 versus tool hits 28.
    Those hit counts alone cannot distinguish a discovery miss from a
    passage rejected by the confidence gate. Raw scores preserve that evidence.
    """
    queries = [
        {"query": case["query"], "expected": case["memory"]} for case in corpus
    ] + [{"query": row["query"], "expected": None} for row in negatives]
    # source: recall_pipeline.familiarity_triage uses this encoder's bytes
    # with hopfield.cosine_similarity (ADR-0235). Measure the existing signal,
    # without introducing a cosine threshold or changing injection decisions.
    vectors = {case["memory"]: _neural_vector(case["memory"]) for case in corpus}
    return [_score_query(case, corpus, vectors) for case in queries]
