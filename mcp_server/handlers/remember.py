"""Handler: remember — store a memory through the flat 4-signal predictive coding gate.

Composition root: wires core modules + infrastructure storage + embeddings.
"""

from __future__ import annotations

from typing import Any

from mcp_server.core import capture_origin
from mcp_server.core import (
    thermodynamics,
    write_gate,
    write_class as write_class_module,
)
from mcp_server.errors import ValidationError
from mcp_server.handlers._telemetry_wrap import instrument
from mcp_server.core.domain_detector import detect_domain
from mcp_server.core.global_detector import detect_global
from mcp_server.handlers.remember_helpers import (
    apply_modulations,
    evaluate_gate,
    insert_and_post_process,
    try_block_replica_upsert,
    try_curation,
    update_user_mood_ema,
    validate_supersede_target,
)
from mcp_server.handlers.remember_response import build_merge_response
from mcp_server.handlers.remember_schema import schema
from mcp_server.infrastructure import wiki_store
from mcp_server.infrastructure.config import WIKI_ROOT
from mcp_server.infrastructure.embedding_engine import get_embedding_engine
from mcp_server.infrastructure.memory_config import (
    get_memory_settings,
    root_agent_topic,
)
from mcp_server.infrastructure.memory_store import MemoryStore, get_shared_store
from mcp_server.infrastructure.profile_store import load_profiles
from mcp_server.shared.domain_mapping import resolve_cwd, resolve_domain as resolve_hint
from mcp_server.shared.content_hardening import harden_content

__all__ = ["schema", "handler"]

_store: MemoryStore | None = None


def _get_store() -> MemoryStore:
    global _store
    if _store is None:
        s = get_memory_settings()
        _store = get_shared_store(s.DB_PATH, s.EMBEDDING_DIM)
    return _store


def _resolve_domain(directory: str, domain: str) -> str:

    # Shannon: cwd is the minimum sufficient statistic for domain identity.
    # Try git-root resolution first (most reliable), then profile detection fallback.
    if directory:
        resolved = resolve_cwd(directory)
        if resolved:
            return resolved
    if domain:
        return resolve_hint(domain)
    if directory:
        # Fallback to profile-based detection
        profiles = load_profiles()
        detection = detect_domain({"cwd": directory}, profiles)
        detected = detection.get("domain", "") or ""
        return resolve_hint(detected) if detected else ""
    return ""


def _enrich_mod_with_gate(mod: dict, gate: dict) -> None:
    """Copy gate signals into the modulation dict for response building."""
    mod.update(
        {
            "gate_reason": gate["gate_reason"],
            "emb_nov": gate["emb_nov"],
            "ent_nov": gate["ent_nov"],
            "temp_nov": gate["temp_nov"],
            "struct_nov": gate["struct_nov"],
        }
    )


def _parse_args(
    args: dict[str, Any],
) -> tuple[str, list, str, str, bool, str, bool, str | None, float | None, str | None]:
    """Extract and default handler arguments.

    Second-to-last element `initial_heat` is the optional age-adjusted
    baseline used by backfill / import paths (issue #14 P1). None = legacy
    1.0 baseline. Defensive clamp to [0, 1] — schema validation enforces
    the same bounds.

    Last element `write_class` is the raw, UNVALIDATED explicit class
    argument (M-D2, 7.4) — None when the caller omitted it. Validation
    happens in `_handler_impl` (the write-time contract), not here.
    """
    raw_initial = args.get("initial_heat")
    initial_heat: float | None = None
    if raw_initial is not None:
        try:
            initial_heat = max(0.0, min(1.0, float(raw_initial)))
        except (TypeError, ValueError):
            initial_heat = None
    return (
        args["content"],
        args.get("tags", []),
        args.get("directory", ""),
        args.get("source", "user"),
        args.get("force", False),
        args.get("agent_topic", ""),
        args.get("is_global", False),
        args.get("created_at"),
        initial_heat,
        args.get("write_class"),
    )


async def _handler_impl(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Store a memory with thermodynamic properties and predictive coding gate."""
    if not args or not args.get("content"):
        return {"stored": False, "action": "rejected", "reason": "no_content"}

    # Phase 7: harden user-controlled content at the ingestion boundary
    # (NFC normalization, control/bidi strip, byte cap).

    args["content"] = harden_content(args["content"])
    if not args["content"]:
        return {"stored": False, "action": "rejected", "reason": "no_content"}

    # Connection-rooted scoping: a server launched with
    # CORTEX_ROOT_AGENT_TOPIC forces that scope on every write, so the
    # model cannot store into (or omit) another agent's scope. Mirrors
    # the recall-side force; covers all callers, not just the tool surface.
    _root = root_agent_topic()
    if _root is not None:
        args["agent_topic"] = _root

    (
        content,
        tags,
        directory,
        source,
        force,
        agent_topic,
        is_global,
        created_at,
        initial_heat,
        write_class_arg,
    ) = _parse_args(args)

    # M-D2 (7.4) write-time contract: an explicit write_class the caller
    # provided is VALIDATED here, at the composition root — never silently
    # reinterpreted (mandate, user 2026-07-11). `validate_write_class` is
    # pure core/ logic that raises plain ValueError; this handler layer is
    # the one allowed to import errors/ (Clean Architecture dependency
    # rule: core/ -> shared/ only), so it re-raises as ValidationError.
    # Omitted (None) is accepted — resolved below via the same single
    # choke point (classify_write_class), source-fallback to 'deliberate'.
    try:
        write_class_module.validate_write_class(write_class_arg)
    except ValueError as exc:
        raise ValidationError(
            str(exc), {"tool": "remember", "field": "write_class"}
        ) from exc
    resolved_write_class = write_class_module.classify_write_class(
        {"write_class": write_class_arg, "source": source}
    )

    store, emb_engine = _get_store(), get_embedding_engine()

    # Explicit supersession target (PRD dual-access increment 1, item ①):
    # fail fast before any embedding/gate work when the target is missing
    # or already superseded — an existing chain is never forked silently.
    supersedes_id, supersede_rejection = validate_supersede_target(
        args.get("supersedes_id"), store
    )
    if supersede_rejection is not None:
        return supersede_rejection

    domain = _resolve_domain(directory, args.get("domain", ""))
    # i7d3 pivot (2026-07-11): the STORED embedding is raw content —
    # unchanged from pre-M-D1 behavior. Template normalization is scoped
    # to the write-gate's novelty DECISION only (evaluate_gate, below),
    # never to what lands in the `embedding` column or the recall vector
    # space. See core/capture_template_normalize.py's module docstring
    # for the incident that narrowed the scope from "normalize the
    # stored embedding" to "normalize the novelty signal only".
    embedding = emb_engine.encode(content)
    valence = thermodynamics.compute_valence(content)

    # issue #365: the CHANNEL the content arrived through, resolved from the
    # producing tool name the caller reports out-of-band — never inferred from
    # the content, which an off-machine payload controls. Governs only whether
    # the content-derived write-gate bypasses may be claimed.
    resolved_origin = capture_origin.classify_capture_origin(
        str(args.get("origin_tool") or "")
    )

    gate = evaluate_gate(
        content,
        tags,
        embedding,
        force,
        store,
        emb_engine,
        domain=domain,
        write_class=resolved_write_class,
        origin=resolved_origin,
    )
    if not gate["should_store"]:
        return write_gate.build_rejection_response(
            gate["emb_nov"],
            gate["ent_nov"],
            gate["temp_nov"],
            gate["struct_nov"],
            gate["score"],
            gate["gate_reason"],
            gate["importance"],
        )

    # Baseline heat defaults to 1.0. Callers may pass an explicit initial_heat
    # to set a different baseline; age-based decay is NOT applied here — it is
    # the read-time job of effective_heat() via the heat_base_set_at anchor
    # (A3 decay clock), keeping a single canonical age-decay path. Surprise
    # boost applies on top.
    baseline_heat = initial_heat if initial_heat is not None else 1.0
    heat = thermodynamics.apply_surprise_boost(
        baseline_heat, gate["score"], get_memory_settings().SURPRISE_BOOST
    )
    mod = apply_modulations(
        content,
        tags,
        heat,
        gate["importance"],
        valence,
        domain,
        gate["ent_names"],
        gate["known"],
        store,
    )
    _enrich_mod_with_gate(mod, gate)

    # Auto-detect global when not explicitly set
    if not is_global:
        is_global, _global_score, global_reason = detect_global(content, tags)
    else:
        global_reason = "explicit"

    mid: int | None
    if supersedes_id is not None:
        # Explicit supersession: the caller's intent overrides automatic
        # curation (no merge/link second-guessing) and the block-replica
        # upsert. force=True composes with it — the gate was bypassed
        # above, yet the edge is still posted below (sovereign human
        # correction; previously force and supersede were exclusive
        # because force early-returned "create" inside try_curation).
        action, mid = "supersede", supersedes_id
    else:
        # Block-replica upsert: if the incoming memory is a system-memory block
        # snapshot (tagged 'memory-replica' + 'vpath:…'), refresh the existing row
        # in-place rather than inserting a new one (one row per block file).
        # Normal writes are completely unaffected — this branch exits early on
        # any write that isn't a replica.
        # contract: zetetic-team-subagents memory/contract.md §8b
        upserted, upsert_id = try_block_replica_upsert(
            content, embedding, tags, source, store
        )
        if upserted and upsert_id is not None:
            return {
                "stored": True,
                "memory_id": upsert_id,
                "action": "stored",
                "reason": "block-replica-refreshed",
            }

        action, mid = try_curation(
            content, embedding, force, store, emb_engine, tags, mod["heat"]
        )
        if action == "merge":
            # Mood signal still updates on merge — the user authored the content,
            # whether we keep it as a new row or fold it into an existing one.
            update_user_mood_ema(content, source, store)
            return build_merge_response(mid, domain, mod, gate)

    result = insert_and_post_process(
        content,
        embedding,
        tags,
        source,
        domain,
        directory,
        action,
        mid,
        gate["sims"],
        gate["vec_hits"],
        gate["ent_names"],
        gate["extracted"],
        mod,
        gate["score"],
        store,
        emb_engine,
        agent_context=agent_topic,
        is_global=is_global,
        created_at=created_at,
        write_class=resolved_write_class,
        origin=resolved_origin,
    )
    if is_global and result.get("stored"):
        result["is_global"] = True
        result["global_reason"] = global_reason

    # MOOD_CONGRUENT_RERANK signal-feed (Bower 1981 mood-congruent recall):
    # EMA-update user_mood.valence from VADER compound on user-authored
    # content. Non-user sources are ignored to keep the signal faithful
    # to the user's affective state. See remember_helpers.update_user_mood_ema
    # for the contract and source-discipline notes.
    if result.get("stored"):
        update_user_mood_ema(content, source, store)

    # Promote decision-shaped memories to the authored wiki layer.
    #
    # Contract (E8, post-Taleb fragility audit):
    #   - On success: ``result["wiki_page"]`` is the relative path.
    #   - On classifier rejection: no field added (memory didn't qualify).
    #   - On wiki I/O failure: memory write is already committed; we log
    #     the failure to ``result["warnings"]`` so the caller can observe
    #     the partial failure rather than silently losing the signal.
    #
    # The store write has succeeded by this point; a failure here is a
    # partial-failure, not a total one. Documented in the schema.
    if result.get("stored") and result.get("memory_id") is not None:
        try:
            wiki_path = wiki_store.sync_memory_strict(
                WIKI_ROOT,
                memory_id=result["memory_id"],
                content=content,
                tags=tags,
                domain=domain,
            )
            if wiki_path:
                result["wiki_page"] = wiki_path
        except Exception as exc:  # noqa: BLE001 — partial-failure boundary — wiki-sync failure is surfaced in result['warnings'] with type+message
            # Partial failure — memory is stored but wiki sync failed.
            # Surfacing the exception type + message preserves the ability
            # to diagnose recurring failures (e.g., disk full, path escape).
            warnings = result.setdefault("warnings", [])
            warnings.append(
                {
                    "scope": "wiki_sync",
                    "memory_id": result["memory_id"],
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                }
            )

    return result


# Telemetry-instrumented public entry. Records latency, byte volume,
# and write success/fail per call (Popper C6 read/write ratio audit).
handler = instrument("remember", _handler_impl, result_count_key=None)
