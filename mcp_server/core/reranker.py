"""Cross-encoder reranking via FlashRank ONNX.

FlashRank (ms-marco-MiniLM-L-12-v2) provides fast cross-encoder reranking.
Validated through LongMemEval and LoCoMo where it improves MRR by 5-15%.

CE reranking with alpha blending of first-stage and CE scores is standard
IR practice — linear interpolation of retrieval and CE scores is the common
approach in multi-stage retrieval (Nogueira & Cho, 2019).

Adaptive alpha (EXPERIMENTAL — disabled by default):
    Attempted per-query alpha based on CE score spread (QPP, Shtok et al.,
    TOIS 2012). Hypothesis: high CE spread → CE is confident → boost alpha.
    Results: BEAM -0.002, LME +0.003, LoCoMo -3.8pp MRR / -5.1pp R@10.
    The mechanism cannot distinguish "one great match" from "one outlier".
    Kept as opt-in (adaptive=True) for future experimentation.
    See benchmarks/beam/ablation_results.json for full data.

Sufficient Context gate (Joren et al., ICLR 2025):
    The paper uses an LLM autorater (Gemini 1.5 Pro CoT) to classify whether
    retrieved context is sufficient — not applicable at <200ms retrieval latency.
    This implementation uses a binary threshold gate: if the max CE score
    falls below gate_threshold, all scores are suppressed by a fixed multiplier.

    Platt sigmoid with BENCHMARK-DERIVED A,B — REJECTED (2026-04-03):
    Attempted replacing the binary gate with Platt-calibrated sigmoid
    using hand-picked A, B tuned to max_CE on benchmark data. All benchmarks
    regressed. See reranker_calibration.py for the follow-up: Platt params
    FIT from user rate_memory feedback (different input distribution) are
    applied opt-in via apply_platt=True, default False until benchmark
    re-validation lands.
      A=10, B=-1.5 (inflection 0.15): BEAM 0.479 (-0.148), LoCoMo R@10 92.6% (-5.1pp)
      A=30, B=-1.5 (inflection 0.05): BEAM 0.442 (-0.185)

    ENGINEERING DEFAULTS (not paper-prescribed):
    - alpha=0.70: Base blend weight for CE vs first-stage scores. Empirically
      determined via BEAM ablation (see benchmarks/beam/ablation_results.json):
      0.30→0.511, 0.50→0.529, 0.55→0.535, 0.70→0.542.
    - gate_threshold=0.15: Min CE score to consider retrieval sufficient.
    - suppression=0.1: Score multiplier when gated.

Pure business logic -- lazy-loaded singleton, no persistent I/O.

Model cache directory (fix 2026-07-11, incident: silent reranker skip):
    FlashRank 0.2.10's own default cache_dir is ``/tmp`` (see the
    installed package's ``flashrank/Config.py``: ``default_cache_dir =
    "/tmp"``). macOS periodically purges /tmp; the first process restart
    after a purge hit ``NoSuchFile`` inside ``Ranker.__init__`` -> the
    bare ``except Exception`` below swallowed it with no log line ->
    every subsequent ``rerank_results`` call for the rest of that
    process's life silently returned first-stage-only scores. This ran
    unnoticed through 6 LongMemEval benchmark executions; measured
    impact MRR 0.9163 -> 0.8636 (R@10 nearly unaffected — the metric a
    quick eyeball check would have caught was the one metric this bug
    barely touched). Fix: pass an EXPLICIT, DURABLE ``cache_dir``
    (``~/.cache/flashrank``, honoring ``$XDG_CACHE_HOME`` — see
    ``mcp_server.shared.platform.cache_dir``) instead of the library
    default, and log (not swallow) any load failure. See
    ``reranker_status()`` for the externally-consumable load state this
    fix also introduces.

    FlashRank's own download behavior (verified by reading the installed
    0.2.10 package, not assumed): ``Ranker._prepare_model_dir`` checks
    ``if not self.model_dir.exists()`` and, when absent, downloads +
    unzips the model from Hugging Face
    (``https://huggingface.co/prithivida/flashrank/resolve/main/{model}.zip``)
    into ``cache_dir``. This means a durable ``cache_dir`` is
    self-provisioning: first run in a fresh cache downloads once (~34MB
    for ms-marco-MiniLM-L-12-v2), every subsequent run in the same
    process or a new one reuses the on-disk copy. No custom download
    logic is needed in Cortex; the failure mode this module now logs is
    exactly the cases where that self-provisioning itself fails (no
    network, no write permission, corrupted archive, etc.).
"""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp_server.core import platt_calibration, reranker_calibration
from mcp_server.observability import silent_failure
from mcp_server.shared.platform import cache_dir as _base_cache_dir

logger = logging.getLogger(__name__)

# source: flashrank==0.2.10 installed package, flashrank/Config.py
# model_file_map["ms-marco-MiniLM-L-12-v2"] — verified by reading the
# installed site-packages file directly (see module docstring).
_MODEL_NAME = "ms-marco-MiniLM-L-12-v2"
_MODEL_FILE = "flashrank-MiniLM-L-12-v2_Q.onnx"

# FlashRank downloads its model with a bare ``requests.get(..., stream=True)``
# carrying NO timeout (verified by reading the installed 0.2.10
# ``Ranker._download_model_files``), so a stalled TCP connect blocks the
# calling thread forever rather than raising -- the ``except Exception``
# in ``_ensure_reranker`` cannot engage against a hang. That is not
# hypothetical: CI run 30263190266 (main, Python 3.13, 2026-07-27) hung in
# ``sock.connect`` inside a recall test until pytest-timeout killed the whole
# suite at 300s. ``HF_HUB_OFFLINE``/``TRANSFORMERS_OFFLINE`` do not reach
# FlashRank because it bypasses the ``huggingface_hub`` client entirely, so
# forbidding the fetch needs its own switch.
_OFFLINE_ENV = "CORTEX_RERANKER_OFFLINE"

_flashrank_instance: Any = None
_flashrank_failed: bool = False
_flashrank_load_error: str | None = None


def _offline_requested() -> bool:
    """True when the caller has forbidden a network fetch of the model.

    Precondition: none.
    Postcondition: True iff ``$CORTEX_RERANKER_OFFLINE`` is set to
        anything other than the empty string, "0", "false", or "no"
        (case- and whitespace-insensitive). Unset means False, so
        production keeps FlashRank's self-provisioning first-run
        download that PRIVACY.md documents; only callers that opt in
        (CI test steps, air-gapped installs) get the strict behavior.
    """
    return os.environ.get(_OFFLINE_ENV, "").strip().lower() not in (
        "",
        "0",
        "false",
        "no",
    )


@dataclass(frozen=True)
class RerankerStatus:
    """Snapshot of the FlashRank reranker singleton's load state.

    state is one of "loaded" | "failed" | "not_attempted". model_path is
    the ONNX file ``_ensure_reranker`` reads from (or would read from),
    computed without touching disk — callers that need to confirm the
    file is actually present (e.g. to sha256 it for a bench manifest)
    must stat/hash ``model_path`` themselves.
    """

    state: str
    model_path: str
    error: str | None = None


def reranker_cache_dir() -> Path:
    """Durable on-disk cache directory for the FlashRank ONNX model.

    See module docstring for why FlashRank's own ``/tmp`` default is
    unsafe. Honors ``$XDG_CACHE_HOME`` (via
    ``mcp_server.shared.platform.cache_dir``); falls back to
    ``~/.cache/flashrank`` — the location already adopted de facto (a
    manually-placed copy of the model existed there before this fix).
    """
    return _base_cache_dir() / "flashrank"


def _model_path() -> Path:
    return reranker_cache_dir() / _MODEL_NAME / _MODEL_FILE


def _ensure_reranker() -> Any:
    """Lazy-load FlashRank ONNX reranker (singleton).

    Precondition: none — safe to call unconditionally, any number of
        times, from any thread-unsafe-but-single-process context (module
        state is process-global, matching the existing singleton
        pattern used elsewhere in core — see write_post_store.py).
    Postcondition: returns the cached ``Ranker`` instance once a load has
        succeeded; returns None on any load failure. On the FIRST
        failure only, logs a warning naming the exact cache directory
        searched and the underlying exception — every call thereafter is
        silent (via the ``_flashrank_failed`` flag) to avoid log spam,
        but the state remains introspectable via ``reranker_status()``.
        When ``$CORTEX_RERANKER_OFFLINE`` is set (see
        ``_offline_requested``) and the model file is absent, the
        download is refused and that same failure path is taken —
        bounding what would otherwise be an unbounded network block,
        and degrading to first-stage WRRF scores exactly as a corrupted
        or unreadable cache already does.
    """
    global _flashrank_instance, _flashrank_failed, _flashrank_load_error
    if _flashrank_instance is not None:
        return _flashrank_instance
    if _flashrank_failed:
        return None
    cache = reranker_cache_dir()
    try:
        if _offline_requested() and not _model_path().is_file():
            raise FileNotFoundError(
                f"{_OFFLINE_ENV} is set and the cached model file is absent "
                f"({_model_path()}); refusing to download it, because "
                "FlashRank's fetch has no timeout and would block this "
                "thread indefinitely on a stalled connection"
            )
        from flashrank import Ranker

        _flashrank_instance = Ranker(model_name=_MODEL_NAME, cache_dir=str(cache))
        return _flashrank_instance
    except Exception as exc:
        _flashrank_failed = True
        _flashrank_load_error = str(exc)
        logger.warning(
            "FlashRank reranker failed to load (model=%s, cache_dir=%s): %s "
            "-- production re-ranking is DISABLED for the rest of this "
            "process; recall falls back to first-stage WRRF scores only.",
            _MODEL_NAME,
            cache,
            exc,
        )
        return None


def ensure_reranker_loaded() -> RerankerStatus:
    """Force a load attempt now (if not already attempted) and report status.

    Public entrypoint for preflight checks — e.g. a benchmark harness
    that must fail fast rather than silently score first-stage-only
    results as if they were production quality (the 2026-07-10 incident
    this module's docstring describes). Idempotent: only the first call
    in a process pays the load (or failure) cost.
    """
    _ensure_reranker()
    return reranker_status()


def reranker_status() -> RerankerStatus:
    """Report the FlashRank singleton's current state without triggering a load.

    Precondition: none.
    Postcondition: state == "loaded" iff a prior load succeeded and the
        instance is cached in-process; "failed" iff a prior load raised
        (``error`` carries the exception text); "not_attempted" iff no
        call to ``_ensure_reranker`` / ``ensure_reranker_loaded`` has
        happened yet in this process. Never triggers a load itself.
    """
    model_path = str(_model_path())
    if _flashrank_instance is not None:
        return RerankerStatus(state="loaded", model_path=model_path)
    if _flashrank_failed:
        return RerankerStatus(
            state="failed", model_path=model_path, error=_flashrank_load_error
        )
    return RerankerStatus(state="not_attempted", model_path=model_path)


def model_sha256() -> str | None:
    """Sha256 of the on-disk ONNX weights file, or None if it is absent.

    Used by bench manifests to fingerprint the exact reranker weights a
    run used (mirrors the existing ``embedding_model_revision`` manifest
    field — see benchmarks/reproduce.sh's ``write_manifest``). Reads the
    file in fixed-size chunks to bound memory use regardless of file size.
    """
    path = _model_path()
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _compute_retrieval_confidence(
    ce_scores: list[float],
    gate_threshold: float = 0.15,
    suppression: float = 0.1,
) -> float:
    """Compute confidence that retrieval found relevant results.

    Binary threshold gate: if max CE score >= threshold, results are
    considered sufficient (confidence=1.0). Otherwise, all scores are
    suppressed by a fixed multiplier.

    Platt sigmoid was attempted (2026-04-03) and rejected — see module
    docstring for ablation data showing regression on all benchmarks.

    Args:
        ce_scores: Raw cross-encoder scores from FlashRank.
        gate_threshold: Below this max CE, results are likely irrelevant.
            Hand-tuned (0.15 default).
        suppression: Score multiplier when gated. Hand-tuned (0.1 default).

    Returns:
        float — 1.0 (sufficient context) or suppression (insufficient).
    """
    if not ce_scores:
        return suppression
    max_ce = max(ce_scores)
    if max_ce >= gate_threshold:
        return 1.0
    return suppression


def _compute_adaptive_alpha(
    ce_scores: list[float],
    base_alpha: float,
) -> float:
    """Compute per-query alpha from CE score distribution.

    Based on post-retrieval QPP (Shtok et al., TOIS 2012): the standard
    deviation / spread of retrieval scores predicts whether the retrieval
    system can discriminate relevant from non-relevant documents.

    When CE scores have high spread → CE found clear relevance signal →
    trust CE more (higher alpha). When spread is low → ambiguous result
    → use base alpha (already optimized via ablation).

    IMPORTANT: alpha never drops BELOW base_alpha. Ablation on BEAM shows
    lower alpha hurts (0.30→0.511, 0.50→0.529, 0.70→0.542). And higher
    fixed alpha also hurts (0.80→0.476, 0.90→0.469, 1.00→0.465). The
    adaptive mechanism ONLY boosts alpha when CE has high confidence,
    staying at base_alpha otherwise.

    The boost is conservative: base_alpha + small_delta when CE is confident.
    This prevents the regression seen when alpha_min < base_alpha (which
    degraded LME by -3.9pp MRR).

    Args:
        ce_scores: Raw cross-encoder scores from FlashRank.
        base_alpha: Optimized base alpha (0.70 from BEAM ablation).

    Returns:
        Adaptive alpha in [base_alpha, base_alpha + 0.15].
    """
    if len(ce_scores) < 2:
        return base_alpha

    spread = max(ce_scores) - min(ce_scores)
    # Only boost alpha when CE shows high discriminative power.
    # FlashRank scores are typically in [-1, 1], spread ∈ [0, 2].
    # High spread (>0.5) → CE found clear winner → small alpha boost.
    # Low spread → ambiguous → keep base alpha (don't reduce!).
    max_boost = 0.15  # Conservative: max alpha = base + 0.15 = 0.85
    if spread < 0.3:
        return base_alpha
    # Linear boost above spread=0.3, capped at max_boost
    normalized = min((spread - 0.3) / 0.7, 1.0)
    return min(base_alpha + max_boost * normalized, 1.0)


def _blend_scores(
    candidates: list[tuple[int, float]],
    ce_scores: dict[int, float],
    alpha: float,
    adaptive: bool = True,
    apply_platt: bool = False,
) -> list[tuple[int, float]]:
    """Blend WRRF scores with cross-encoder scores, scaled by confidence.

    Retrieval confidence from raw CE scores gates the final blended score.
    When no result strongly matches (low CE), confidence pulls scores down,
    enabling natural abstention for unanswerable queries.

    When adaptive=True, alpha is adjusted per-query based on CE score
    spread (Shtok et al., TOIS 2012 QPP principle).

    When apply_platt=True AND fitted Platt parameters are available from
    user rate_memory feedback, the CE scores used in the blend are
    replaced by their calibrated probabilities P(useful | raw_score)
    via ``platt_calibration.calibrate_score`` (Platt 1999). When no
    parameters exist (cold start) or apply_platt=False, raw CE scores
    are used unchanged — identical to the pre-AF-2 behaviour.
    """
    raw_ce_list = [ce_scores.get(i, 0.0) for i in range(len(candidates))]
    confidence = _compute_retrieval_confidence(raw_ce_list)

    # Per-query adaptive alpha based on CE score distribution
    effective_alpha = _compute_adaptive_alpha(raw_ce_list, alpha) if adaptive else alpha

    # Optional Platt calibration of the CE dimension of the blend. If the
    # calibrator has no fitted params (cold start), calibrate_score is the
    # identity — the blend matches the pre-AF-2 behaviour exactly.
    platt_params = reranker_calibration.get_params() if apply_platt else None

    reranked = []
    for i, (mem_id, wrrf_score) in enumerate(candidates):
        ce = ce_scores.get(i, 0.0)
        ce_for_blend = platt_calibration.calibrate_score(ce, platt_params)
        blended = (1 - effective_alpha) * wrrf_score + effective_alpha * ce_for_blend
        reranked.append((mem_id, blended * confidence))
    reranked.sort(key=lambda x: x[1], reverse=True)
    return reranked


def rerank_results(
    query: str,
    candidates: list[tuple[int, float]],
    content_lookup: dict[int, str],
    alpha: float = 0.70,
    max_content_len: int = 1200,
    adaptive: bool = False,
    apply_platt: bool = False,
) -> list[tuple[int, float]]:
    """Rerank candidates using FlashRank cross-encoder.

    Args:
        query: Search query text.
        candidates: List of (memory_id, wrrf_score) from first-stage retrieval.
        content_lookup: Map of memory_id → content text.
        alpha: Base blend weight for CE vs first-stage (0.70 from BEAM ablation).
        max_content_len: Maximum content length passed to CE.
        adaptive: If True, adjust alpha per-query based on CE score spread
            (Shtok et al., TOIS 2012 QPP principle). Default False pending
            ablation validation.
        apply_platt: If True AND fitted Platt parameters exist in
            reranker_calibration (>=50 rate_memory pairs collected),
            calibrate CE scores to P(useful|raw_ce) before blending.
            Default False until benchmark re-validation lands — see
            AF-2 ablation note in the module docstring.
    """
    ranker = _ensure_reranker()
    if ranker is None or not candidates:
        return candidates
    try:
        from flashrank import RerankRequest

        passages = [
            {"id": i, "text": content_lookup.get(mid, "")[:max_content_len]}
            for i, (mid, _) in enumerate(candidates)
        ]
        results = ranker.rerank(RerankRequest(query=query, passages=passages))
        ce_scores = {r["id"]: r["score"] for r in results}
        return _blend_scores(
            candidates, ce_scores, alpha, adaptive=adaptive, apply_platt=apply_platt
        )
    except Exception as exc:
        # Distinct failure point from _ensure_reranker's load failure (see
        # module docstring, bb1c581f): the model loaded fine but THIS
        # inference call raised (malformed passage, ONNX runtime error,
        # OOM, ...). Same silent-skip shape, different trigger — must be
        # equally observable.
        silent_failure.note("reranker.rerank_call", exc)
        return candidates


def get_raw_ce_score(
    query: str, content: str, max_content_len: int = 1200
) -> float | None:
    """Return a single raw FlashRank CE score for (query, content).

    Used by ``rate_memory`` to collect Platt training samples: when the
    caller provides the query that surfaced a memory, we re-encode the
    pair at rating time and record (raw_score, useful) for future fits.

    Returns None if FlashRank is unavailable or encoding fails — the
    caller must handle None (typically: skip the sample).
    """
    ranker = _ensure_reranker()
    if ranker is None or not query or not content:
        return None
    try:
        from flashrank import RerankRequest

        results = ranker.rerank(
            RerankRequest(
                query=query,
                passages=[{"id": 0, "text": content[:max_content_len]}],
            )
        )
        if not results:
            return None
        return float(results[0].get("score", 0.0))
    except Exception as exc:
        silent_failure.note("reranker.raw_ce_score", exc)
        return None
