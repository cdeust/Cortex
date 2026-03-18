"""Response builders for the remember handler.

Constructs success, merge, and rejection response dicts.
"""

from __future__ import annotations

from typing import Any

from mcp_server.core import schema_engine
from mcp_server.core.predictive_coding_flat import describe_signals


def build_emotional_info(etag: dict | None) -> dict | None:
    """Extract emotional summary from tag result."""
    if not etag or not etag.get("is_emotional"):
        return None
    return {
        "dominant": etag["dominant_emotion"],
        "arousal": etag["arousal"],
        "boost": etag["importance_boost"],
    }


def build_schema_info(schema_match: float, schema_id: str | None) -> dict | None:
    """Build schema match info if present."""
    if schema_match <= 0:
        return None
    return {
        "match_score": round(schema_match, 4),
        "schema_id": schema_id,
        "pathway": schema_engine.classify_schema_match(schema_match),
    }


def _build_mechanism_fields(mod: dict, sep: float, interf: float) -> dict:
    """Build oscillatory, consolidation, separation, and schema fields."""
    return {
        "neuromodulation": mod["neuro_mod"],
        "emotional_tag": build_emotional_info(mod["emotional_tag"]),
        "oscillatory": {
            "theta_phase": round(mod["theta"], 4),
            "encoding_strength": round(mod["enc_mod"], 4),
        },
        "consolidation_stage": "labile",
        "pattern_separation": {
            "separation_index": round(sep, 4),
            "interference_score": round(interf, 4),
        },
        "schema": build_schema_info(mod["schema_match"], mod["schema_id"]),
    }


def build_response(
    mem_id: int,
    action: str,
    stype: str,
    domain: str,
    mod: dict,
    score: float,
    tids: list,
    extracted: list,
    slot: dict | None,
    tagged: list,
    sep: float,
    interf: float,
) -> dict[str, Any]:
    """Build the full success response dict."""
    result = {
        "stored": True,
        "memory_id": mem_id,
        "action": action,
        "store_type": stype,
        "domain": domain,
        "heat": round(mod["heat"], 4),
        "importance": round(mod["importance"], 4),
        "valence": round(mod["valence"], 4),
        "reason": mod.get("gate_reason", "novel"),
        "novelty": describe_signals(
            mod["emb_nov"],
            mod["ent_nov"],
            mod["temp_nov"],
            mod["struct_nov"],
            score,
        ),
        "triggers_created": tids,
        "entities_extracted": len(extracted),
        "engram": slot,
        "synaptic_tags": len(tagged),
    }
    result.update(_build_mechanism_fields(mod, sep, interf))
    return result


def build_merge_response(
    mid: int | None,
    domain: str,
    mod: dict,
    gate: dict[str, Any],
) -> dict[str, Any]:
    """Build the response for a merge action."""
    return {
        "stored": True,
        "memory_id": mid,
        "action": "merged",
        "domain": domain,
        "heat": round(mod["heat"], 4),
        "importance": round(mod["importance"], 4),
        "novelty": describe_signals(
            gate["emb_nov"],
            gate["ent_nov"],
            gate["temp_nov"],
            gate["struct_nov"],
            gate["score"],
        ),
        "reason": "merged_with_existing",
    }
