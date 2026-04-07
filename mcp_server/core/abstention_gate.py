"""Retrieval abstention gate using cortex-beam-abstain model.

Filters retrieval results that don't actually answer the query.
The model is a fine-tuned DistilBERT trained on BEAM (query, passage,
relevant/irrelevant) pairs with hard-negative mining.

When the model is unavailable, falls back to no-op (returns results
unchanged) — never breaks retrieval.

Source model: github.com/cdeust/cortex-know-when-to-stop-training-model

Pure business logic — no I/O beyond model inference.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Singleton — one model loaded per process
_classifier = None
_load_attempted = False

# Calibrated thresholds (from v0.1 model evaluation):
#   Score range on diverse queries: 0.215 - 0.830
#   F1-optimal threshold: 0.45
#   Precision-optimal threshold: 0.55
#   Recall-optimal threshold: 0.35
DEFAULT_THRESHOLD = 0.45


def _get_classifier() -> Any:
    """Lazy-load the abstention classifier.

    Returns None if the model isn't available — caller should treat
    that as "no filtering" (return all results unchanged).
    """
    global _classifier, _load_attempted

    if _classifier is not None:
        return _classifier
    if _load_attempted:
        return None

    _load_attempted = True
    try:
        # Lazy import — package is optional
        from cortex_beam_abstain import AbstentionClassifier

        cache = Path.home() / ".cache" / "cortex-abstention" / "model.onnx"
        if cache.exists():
            _classifier = AbstentionClassifier(model_path=cache)
        else:
            _classifier = AbstentionClassifier()  # auto-download
        logger.info("Abstention classifier loaded")
    except ImportError:
        logger.debug(
            "cortex-beam-abstain not installed; abstention gate disabled. "
            "Install: pip install cortex-beam-abstain"
        )
        _classifier = None
    except Exception as e:
        logger.warning("Failed to load abstention classifier: %s", e)
        _classifier = None

    return _classifier


def filter_by_abstention(
    query: str,
    candidates: list[dict[str, Any]],
    threshold: float = DEFAULT_THRESHOLD,
    keep_at_least: int = 0,
) -> tuple[list[dict[str, Any]], list[float]]:
    """Filter retrieval results using the abstention classifier.

    Args:
        query: The original query text.
        candidates: Retrieved memory dicts with 'content' field.
        threshold: Minimum relevance score to keep a result.
            Default 0.45 (F1-optimal from v0.1 evaluation).
        keep_at_least: Always return at least this many results,
            even if all score below threshold. 0 = strict filtering
            (may return empty list = abstention).

    Returns:
        (filtered_candidates, scores) tuple. The scores list parallels
        the original candidates order before filtering, useful for
        diagnostics and threshold tuning.
    """
    if not candidates:
        return [], []

    clf = _get_classifier()
    if clf is None:
        # Model unavailable — return everything unchanged
        return candidates, [1.0] * len(candidates)

    # Score each (query, content) pair
    pairs = [(query, c.get("content", "")) for c in candidates]
    scores = clf.predict_batch(pairs)

    # Filter by threshold
    kept = [
        c for c, s in zip(candidates, scores, strict=False) if s >= threshold
    ]

    # If filtering removed everything but caller wants minimum results,
    # keep top-N by score regardless of threshold
    if len(kept) < keep_at_least and candidates:
        ranked = sorted(
            zip(candidates, scores, strict=False),
            key=lambda x: x[1],
            reverse=True,
        )
        kept = [c for c, _ in ranked[:keep_at_least]]

    return kept, scores


def should_abstain(
    query: str,
    candidates: list[dict[str, Any]],
    threshold: float = DEFAULT_THRESHOLD,
) -> bool:
    """Quick check: should the system return empty results entirely?

    True when ALL candidates score below threshold (no relevant match).
    """
    filtered, _ = filter_by_abstention(query, candidates, threshold)
    return len(filtered) == 0
