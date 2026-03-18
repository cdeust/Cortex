"""Stage 5: Verification — claim decomposition, verification, debate, consensus."""

from __future__ import annotations

from typing import Any

from mcp_server.errors import AnalysisError
from mcp_server.handlers.pipeline.helpers import log, trunc


async def _decompose_and_verify(client, top_finding: dict) -> tuple[int, dict]:
    """Decompose claims and run single-claim verification."""
    content = (
        f"{top_finding.get('title')}: {trunc(top_finding.get('description'), 400)}"
    )

    decomp = await client.call(
        "ai_architect_decompose_claim",
        {
            "content": content,
            "priority": 80,
        },
    )
    claim_count = (
        (decomp.get("claim_count") or len(decomp.get("claims", [])) or 1)
        if isinstance(decomp, dict)
        else 1
    )

    verify = await client.call(
        "ai_architect_verify_claim",
        {
            "content": content,
            "claim_type": "atomic_fact",
            "context": f"Source: {top_finding.get('source_url', 'TechnicalVeil')}. Actor: {top_finding.get('actor')}",
            "priority": 80,
        },
    )
    return claim_count, verify


def _safe_score(d: dict | Any, key: str, default: float) -> float:
    """Extract a score from a dict, returning default if not a dict."""
    return d.get(key, default) if isinstance(d, dict) else default


async def _debate_and_fuse(
    client,
    top_finding: dict,
    verify: dict,
) -> tuple[dict, dict, dict]:
    """Run debate, consensus, and confidence fusion."""
    debate = await client.call(
        "ai_architect_debate_claim",
        {
            "content": f"{top_finding.get('title')}: {trunc(top_finding.get('description'), 300)}",
            "num_agents": 3,
            "max_rounds": 2,
        },
    )

    v_score = _safe_score(verify, "score", 0.75)
    v_conf = _safe_score(verify, "confidence", 0.8)
    d_score = _safe_score(debate, "overall_score", 0.7)

    consensus = await client.call(
        "ai_architect_consensus",
        {
            "scores": [v_score, d_score],
            "confidences": [v_conf, 0.7],
            "method": "adaptive_stability",
        },
    )

    fusion = await client.call(
        "ai_architect_fuse_confidence",
        {
            "estimates": [
                {
                    "source": "cov",
                    "value": v_score,
                    "uncertainty": 1.0 - v_conf,
                    "reasoning": "Claim verification",
                },
                {
                    "source": "debate",
                    "value": d_score,
                    "uncertainty": 0.3,
                    "reasoning": "Multi-agent debate",
                },
            ],
        },
    )
    return debate, consensus, fusion


def _check_verdict(verify: dict, debate: dict) -> None:
    """Raise AnalysisError if verification scores are too low."""
    v_score = verify.get("score", 0.75) if isinstance(verify, dict) else 0.75
    d_score = debate.get("overall_score", 0.7) if isinstance(debate, dict) else 0.7
    avg_score = (v_score + d_score) / 2

    verdict = verify.get("verdict") if isinstance(verify, dict) else None
    if verdict in ("fail", "reject"):
        raise AnalysisError(
            f"Verification rejected finding: {verdict} (score: {v_score})",
            {"stage": 5, "verify": verify},
        )
    if avg_score < 0.5:
        raise AnalysisError(
            f"Verification scores too low: verify={v_score:.2f}, "
            f"debate={d_score:.2f}, avg={avg_score:.2f}",
            {"stage": 5},
        )


async def stage_verification(client, ctx: dict) -> None:
    """Execute the full verification stage."""
    log("Stage 5: Verification")
    top_finding = ctx["topFindings"][0]

    claim_count, verify = await _decompose_and_verify(client, top_finding)
    debate, consensus, fusion = await _debate_and_fuse(client, top_finding, verify)

    await client.call(
        "ai_architect_save_context",
        {
            "stage_id": 5,
            "finding_id": ctx["findingId"],
            "artifact": {
                "decomp_claims": claim_count,
                "verify": verify,
                "debate_score": debate.get("overall_score", 0.7)
                if isinstance(debate, dict)
                else 0.7,
                "consensus": consensus,
                "fusion": fusion,
            },
        },
    )

    _check_verdict(verify, debate)

    v_score = verify.get("score", 0.75) if isinstance(verify, dict) else 0.75
    verdict = verify.get("verdict") if isinstance(verify, dict) else None

    ctx.update(
        {"verify": verify, "debate": debate, "consensus": consensus, "fusion": fusion}
    )
    ctx["stages"][5] = {
        "status": "ok",
        "verdict": verdict,
        "score": v_score,
        "claims": claim_count,
    }
    log(f"  verdict: {verdict} (score: {v_score})")
