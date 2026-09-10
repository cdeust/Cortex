# ADR-0431: mcp_server/handlers/recall_helpers.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/handlers/recall_helpers.py`; original SHA-256 `016549007020f147a854e8ea79a87f1dd37ccec7fbd2d35e50bab52c514d9e4c`.

## Original docstring, lines 1–4

````text
"""Helpers for the recall handler — signal collection and result building.

Extracted to keep recall.py under 300 lines with all methods under 40 lines.
"""
````

## Original comment, lines 51–55

````text
# Code-aware discovery (issue #169): a camelCase/snake_case query term is
    # expanded into its sub-tokens so a lowercase query ("payment") recalls a
    # symbol memory ("normalizePaymentAmount") on the SQLite FTS path — and vice
    # versa. Merge-in only (never removes a hit); the raw/expanded searches
    # above stay primary, so this is additive on both backends.
````

## Original comment, lines 164–176

````text
# Low-signal tags: memories so tagged are auto-captures from tool
# operations, backfill imports, or stage reports — useful for audit
# replay but noise in semantic recall.
#
# Spike 2026-05-13: three diverse queries about ADR-2244 design
# decisions returned exclusively ``# Tool: Edit`` captures from
# unrelated repos. The curated wiki (31 ADRs + 21 lessons + 54
# conventions) was drowned out because every captured tool call
# scores high on WRRF + heat + recency.
#
# The wiki classifier (``mcp_server.core.wiki_classifier_patterns.AUDIT_TAGS``)
# already maintains this concept and rejects such content from the
# wiki. Recall reuses the same idea at the retrieval layer.
````

## Original docstring, lines 310–326

````text
"""Inject prospective memories whose triggers match the query.

    Standing instructions like "Always X when I ask about Y" are stored
    as prospective memories. When a query matches their trigger, the
    associated memory is injected into results even if WRRF didn't find it.

    Bounded-io Phase 2 F1 (docs/provenance/bounded-io-phase2-design.md M1): the
    2026-06-10 audit found this injection was the PRIMARY live scoring
    inversion — 317 garbage triggers each prepending up to 3 FTS matches
    at a fabricated 0.9, unbounded, re-introducing the exact auto-capture
    blobs filter_low_signal had just dropped. Now: injected candidates
    respect the same low-signal taxonomy (LOW_SIGNAL_TAGS + auto-capture
    source), the total is capped at ``max_inject`` (the caller-requested
    k — injection must not exceed the tool's response contract), and each
    item carries ``injected: True`` so the fabricated 0.9 is observable
    as trigger metadata, not a covert rank.
    """
````

## Original docstring, lines 372–377

````text
"""Trigger injection must not bypass the low-signal discipline.

    Auto-captured tool dumps and tag-marked noise are exactly what
    filter_low_signal removes from the ranked results upstream;
    re-inserting them here at a fixed 0.9 inverted the ranking.
    """
````

## Original docstring, lines 483–504

````text
"""Surface C1 source/reality-monitoring provenance on each recall hit, in place.

    Additive read-side surfacing of the ``source_attribution`` the recall
    projection now returns (pg_schema.recall_memories → pg_store dict → here):

      - ``source_attribution`` — the memory's stored epistemic origin
        (perceived / told / inferred / unknown), defaulted to 'unknown' when the
        column/value is absent (older store or un-classified row).
      - ``confabulation_risk`` — the per-hit reality-monitoring flag
        (``source_monitoring.recall_confabulation_risk``): True only when the
        memory was stored as PERCEIVED but its content now classifies as INFERRED
        with zero perceptual grounding (Johnson & Raye 1981). A memory stored as
        inferred/told/unknown makes no external-grounding promise and is never
        flagged.

    STRICTLY ADDITIVE: it only writes those two keys onto each existing result
    dict; it never reorders, drops, or injects results. Disabled when
    ``Mechanism.CONFABULATION_GATE`` is ablated
    (``CORTEX_ABLATE_CONFABULATION_GATE=1``) — in that case each hit still gets
    its ``source_attribution`` (pure provenance passthrough) but ``confabulation
    _risk`` is left False, so the gate contributes nothing to the response.
    """
````

