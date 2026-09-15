"""Retrieval abstention gate using cortex-beam-abstain model.

source: ADR-0097"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

# Singleton — one model loaded per process
_classifier = None
_load_attempted = False

# source: ADR-0097


DEFAULT_THRESHOLD = 0.45

# A classifier factory performs filesystem I/O (model cache lookup, possible
# download) and therefore must be supplied by the composition root — see
# mcp_server.infrastructure.abstention_classifier.load_abstention_classifier.
# source: issue #560 (core/ may not import os/pathlib)
ClassifierFactory = Callable[[], Any | None]


def _get_classifier(classifier_factory: ClassifierFactory | None) -> Any:
    """Lazy-load the abstention classifier via an injected factory.

    Precondition: ``classifier_factory``, when provided, returns a loaded
    classifier or ``None`` on failure/absence; it may perform I/O (that I/O
    lives in infrastructure/, never here).
    Postcondition: memoizes the first non-``None`` result (or the fact that
    loading was attempted) in module state, exactly as before this seam was
    introduced — the "reads/attempts once per process" caching semantics
    are unchanged. Returns ``None`` if the model isn't available or no
    factory was given — caller should treat that as "no filtering" (return
    all results unchanged).
    """
    global _classifier, _load_attempted

    if _classifier is not None:
        return _classifier
    if _load_attempted:
        return None

    _load_attempted = True
    if classifier_factory is None:
        return None
    _classifier = classifier_factory()
    if _classifier is not None:
        logger.info("Abstention classifier loaded")
    return _classifier


def filter_by_abstention(
    query: str,
    candidates: list[dict[str, Any]],
    threshold: float = DEFAULT_THRESHOLD,
    keep_at_least: int = 0,
    classifier_factory: ClassifierFactory | None = None,
) -> tuple[list[dict[str, Any]], list[float]]:
    """Filter retrieval results using the abstention classifier.

    Args:
        query: The original query text.
        candidates: Retrieved memory dicts with 'content' field.
        threshold: Minimum relevance score to keep a result (default 0.45).
        keep_at_least: Minimum results retained, even below the threshold;
            zero enables strict filtering and may return no results.
        classifier_factory: Composition-root-supplied loader (see
            mcp_server.infrastructure.abstention_classifier); omit to run
            with abstention filtering disabled (candidates pass through
            unchanged), e.g. in tests.
    source: ADR-0097

    Returns:
        (filtered_candidates, scores) tuple. The scores list parallels
        the original candidates order before filtering, useful for
        diagnostics and threshold tuning.
    """
    if not candidates:
        return [], []

    clf = _get_classifier(classifier_factory)
    if clf is None:
        # Model unavailable — return everything unchanged
        return candidates, [1.0] * len(candidates)

    # Score each (query, content) pair
    pairs = [(query, c.get("content", "")) for c in candidates]
    scores = clf.predict_batch(pairs)

    # Filter by threshold
    kept = [c for c, s in zip(candidates, scores, strict=False) if s >= threshold]

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
    classifier_factory: ClassifierFactory | None = None,
) -> bool:
    """Quick check: should the system return empty results entirely?

    True when ALL candidates score below threshold (no relevant match).
    """
    filtered, _ = filter_by_abstention(
        query, candidates, threshold, classifier_factory=classifier_factory
    )
    return len(filtered) == 0
