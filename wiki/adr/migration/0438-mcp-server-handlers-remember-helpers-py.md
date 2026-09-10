# ADR-0438: mcp_server/handlers/remember_helpers.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/handlers/remember_helpers.py`; original SHA-256 `29998a09bdd99fe07fe295ed98f1aed9c19142b79614d79a12d716958d6835d2`.

## Original docstring, lines 1–4

````text
"""Helpers for the remember handler — gate evaluation, modulation, curation, storage.

Extracted to keep remember.py under 300 lines with all methods under 40 lines.
"""
````

## Original comment, lines 57–60

````text
# Textual-overlap fraction above which a near-duplicate candidate counts
# as overlapping for the curation decision.
# source: pre-existing tuned value, extracted unchanged (#197 family 3);
# provenance not recorded at introduction
````

## Original comment, lines 82–84

````text
# heads_only: novelty must be scored against CURRENT knowledge —
        # against a dead superseded version, a legitimate re-write of the
        # corrected fact would be gated out as "not novel".
````

## Original docstring, lines 102–108

````text
"""Preserve the scalar normalized-space scoring contract exactly.

    source: docs/provenance/green-w3-2-encoding-identity.md — the measured
    neural batch changes scores, so it fails the strict W3-2 contract.
    Normalization belongs only to gate novelty; stored vectors remain raw.
    Preserve candidate order, absent-vector behavior and exception propagation.
    """
````

## Original docstring, lines 142–160

````text
"""Hierarchical free-energy novelty score in [0, 1].

    Routes the same content/entity/recent-memory evidence the flat path uses
    through the 3-level predictive hierarchy (Friston 2005) and returns the
    sigmoid ``novelty_score``, which is on the identical [0, 1] scale as
    ``compute_novelty_score`` — so the gate threshold and calibration EMA are
    unaffected by the choice of scorer. Schema level (L2) uses the neutral
    default schema_match here because schema matching runs after the gate
    (apply_modulations).

    MEASURED LIMITATION (benchmarks/gate_precision, 2026-06-11): this scorer
    does NOT separate novel content from duplicates of stored content —
    ROC-AUC 0.5514 vs 0.9998 for the flat path. The neutral L2 default makes
    its free energy a constant 1.5, flooring the score above the default
    threshold for all content, and no level sees embedding similarity to the
    nearest stored neighbor (the flat path's dominant duplicate signal).
    Kept behind WRITE_GATE_HIERARCHICAL=False pending an L0/L2 redesign;
    any change must re-run benchmarks/gate_precision/run_benchmark.py.
    """
````

## Original comment, lines 211–211

````text
# source: evaluate_gate at a284e473, the existing current-knowledge window.
````

## Original comment, lines 417–420

````text
# Same shape as the spread_activation incident: a broken SELECT
        # here is indistinguishable from "no existing block row", so the
        # caller silently falls through to inserting a DUPLICATE row
        # instead of superseding — must be observable, not just absorbed.
````

## Original comment, lines 478–479

````text
# This search includes old heads. Read their current supersession state
        # after the search rather than reuse the earlier novelty-gate snapshot.
````

## Original comment, lines 489–494

````text
# Head-check: never merge/link into (or supersede) a superseded
            # version — the write would be buried in a row the read path
            # excludes. No signal is lost: the chain head is near-identical
            # in embedding and remains in the candidate set. Mirrors the
            # write-path guards (validate_supersede_target rejects superseded
            # targets; supersede_atomic rebases via _current_chain_head).
````

## Original comment, lines 504–510

````text
# A near-duplicate that CONTRADICTS the existing fact is a
                # knowledge update, not a duplicate. Retain both rows and
                # record an explicit supersession edge instead of folding
                # the old content away (merge is destructive → would lose
                # "what did X say before?"). Contradiction signal is the
                # existing committed heuristic (negation mismatch / action
                # divergence) — no new constants introduced here.
````

## Original comment, lines 533–538

````text
# i7d3 pivot: the stored embedding stays raw content, same as
    # remember.py's write path — see that module's comment for the
    # incident/decision this reverted.
    # Reuse only this write's raw vector for byte-for-byte identical text.
    # A changed merge still needs its own encode; an older candidate vector
    # may belong to a different model/fallback and is not interchangeable.
````

## Original comment, lines 586–605

````text
# C1 source / reality monitoring: attribute the memory's epistemic origin
    # (perceived / told / inferred) from its content + ingestion pathway, so a
    # self-generated inference is not stored indistinguishably from a file-
    # grounded observation (Johnson, Hashtroudi & Lindsay 1993). Best-effort —
    # a classification failure must never block a write.
    #
    # I6-D6 note (kept, not neutralized — écriture initiale != grade): this
    # write is an EPISTEMIC-ORIGIN classification (perceived/told/inferred/
    # unknown, Johnson 1993), not a verifiability GRADE (verified/verifiable/
    # unverifiable, core/provenance.py). validate_memory.py is the sole writer
    # of the GRADE vocabulary and OVERWRITES whatever value is here the next
    # time it verifies this memory — so this column transiently holds C1's
    # epistemic tag for a freshly-written, not-yet-verified memory, and the
    # verifier's grade for a memory that has been through a validate_memory
    # pass. Neutralizing this write outright would silently disable the
    # confabulation gate (recall_helpers.annotate_source_attribution,
    # consolidation_engine promotion gate) — a live, tested, academically-
    # sourced feature (Johnson & Raye 1981) the I6-D6 design did not account
    # for (it landed on this column after the design's audit commit). See
    # /memories/engineer/inc6.5-provenance-verifier.md for the full rationale.
````

## Original docstring, lines 638–661

````text
"""Append link provenance to a to-be-created memory's tags.

    Precondition: `tags` is about to be written on a NEW row (this is called
    before `store.insert_memory`/`store.supersede_atomic`, so no memory id
    exists yet for the row being built); `action`/`merged_id` come from
    `try_curation`'s "link" decision (near-duplicate, not merged/superseded).
    Postcondition: when `action == "link"` and `merged_id` is set, returns
    `tags` plus a `link-derived` category tag and a `derived-src:<merged_id>`
    pointer to the memory this row is a near-duplicate/derivative of;
    otherwise returns `tags` unchanged.

    Tags, not a `relationships` row: `relationships.source_entity_id` /
    `target_entity_id` are `NOT NULL REFERENCES entities(id)` and cannot
    address a memory id. The prior implementation (`_link_if_needed`,
    replaced here) called `store.insert_relationship({"source_entity_id":
    mem_id, "target_entity_id": merged_id, ...})` inside a bare
    `except Exception: pass` — every "link" write raised the FK violation and
    was silently swallowed, so no link was ever persisted since this code's
    introduction. Fixed at the source: provenance is now embedded in the
    row's own tags at insert time (before the row exists, so no post-hoc
    update is needed either), reusing the `derived-src:<memory_id>`
    convention already established and live-proven by
    `handlers/consolidation/memify_derive.py` (INC6.1b).
    """
````

## Original docstring, lines 693–701

````text
"""Result of a best-effort write-time provenance grading pass.

    ``resolution_root``/``resolution_root_explicit``/``resolution_root_exists``
    (issue #345) are the caller-side context ``core/provenance.write_time_hint``
    needs to distinguish "reference genuinely dead" from "reference resolved
    against the wrong root" -- core/ stays zero-I/O (module docstring), so
    the ``os.path.isdir`` check that produces ``resolution_root_exists``
    happens here, in the handlers layer.
    """
````

## Original docstring, lines 725–749

````text
"""Best-effort wrapper around ``validate_memory.grade_from_content``.

    Root cause (issue #147): ``grade_from_content``'s ``base_dir`` fallback
    calls ``os.getcwd()``, which raises ``FileNotFoundError`` when the
    process's current working directory no longer exists (e.g. a worktree
    the session was running in got cleaned up). Every OTHER enrichment step
    in this insert path (``source_attribution`` classification, the
    habituation signature) is already wrapped defensively; this call was
    the sole exception -- an unguarded I/O-adjacent call inside what the
    surrounding function's own contract calls a best-effort pass. Fixed at
    the source by matching the established local pattern instead of
    special-casing ``os.getcwd()``.

    Postcondition: NEVER raises. Always returns a ``_GradeContext`` whose
    ``resolution_root_explicit`` is ``bool(directory)`` -- issue #345:
    when the caller passed no ``directory``, resolution silently fell back
    to the server process's cwd, which need not be the writer's project
    root (reproduced live on memory 4341427, 2026-08-08: 3 real paths in
    the Cortex repo graded dead because the write's cwd was the repo's
    *parent* directory). On any failure returns a fallback
    ``ProvenanceReport`` graded ``UNVERIFIABLE`` (the same "we don't know"
    default ``grade_provenance`` uses for zero extractable references) plus
    the failing exception's type name, so the caller can surface it as an
    observable tag instead of a silently absorbed enrichment.
    """
````

## Original comment, lines 818–821

````text
# Link provenance is appended AFTER classify_memory so the link marker
    # tags never influence store_type classification, and BEFORE the record
    # is built so the pointer is written atomically with the row (no memory
    # id exists yet to update post-hoc).
````

## Original comment, lines 823–836

````text
# M-D5 (7.5): grade this not-yet-inserted content's provenance with the
    # SAME local-only checks validate_memory's batch pass uses (no network
    # -- see validate_memory.grade_from_content). Persisted as an ADDITIVE
    # TAG (same no-post-hoc-update pattern as _with_link_provenance above),
    # never into `source_attribution` -- that column's grade vocabulary has
    # exactly one writer, validate_memory.py (I6-D6). A second writer there
    # would silently defeat the C1 confabulation gate
    # (core/source_monitoring.py::recall_confabulation_risk), which fires
    # only on the PERCEIVED epistemic tag C1's classify_source writes to
    # that same column below, in _build_insert_record -- see
    # /memories/engineer/inc6.5-provenance-verifier.md. Runs strictly AFTER
    # evaluate_gate() (called by remember.py before this function), so the
    # tag can never influence the novelty/gate decision -- bench-neutral by
    # construction, no G-bench required for this increment.
````

## Original comment, lines 841–848

````text
# issue #147: grade_from_content's os.getcwd() fallback can raise
        # FileNotFoundError when the process cwd has been removed mid-session
        # (e.g. a worktree cleanup) -- unrelated to the DB and unrelated to
        # write_class. This step is documented as best-effort (like every
        # other enrichment in this function -- source_attribution above,
        # habituation signature below); it must never block the insert.
        # Surfaced as an observable tag rather than silently absorbed
        # (coding-standards.md: no silent fallbacks).
````

## Original comment, lines 869–872

````text
# issue #365: persist the CHANNEL the content arrived through, so the
    # value that governed the gate decision is queryable afterwards — the
    # injection-time critique (#363) and `/why` both need it, and an
    # in-flight-only check cannot be audited.
````

## Original comment, lines 915–929

````text
# M-D5 (7.5): surface the write-time provenance grade (transient
    # feedback, never persisted into source_attribution -- see the tag
    # comment above) so the writer sees, in the SAME response, whether
    # their claim carries a checkable reference and can complete it by
    # superseding this memory if not.
    #
    # issue #345: "hint" used to be a pure `grade` lookup that claimed "no
    # checkable reference found" even when `checkable_refs` in this SAME
    # dict counted several -- the diagnosis (`report.reason`/`dead_refs`)
    # was computed and then discarded. `reason`/`dead_refs` are now also
    # surfaced directly (capped at 3, matching `_build_reason`'s own cap --
    # `core/provenance.py`), matching what `validate_memory`'s batch pass
    # already exposes (`handlers/validate_memory.py:559-561`), and the hint
    # itself names the dead refs AND the resolution root they were checked
    # against (`_grade_content_best_effort`'s `_GradeContext`).
````

## Original comment, lines 952–953

````text
# The row actually superseded is the chain head the edge landed on —
        # equal to merged_id unless a concurrent race rebased the write.
````

## Original docstring, lines 961–972

````text
"""Report a supersession that could not converge on a stable chain head.

    Reached only when ``store.supersede_atomic`` exhausts its bounded
    reconsolidation rebase: every attempt lost the compare-and-set to a
    concurrent writer moving the head. Because each attempt runs the insert and
    the edge inside ONE transaction, a lost attempt rolls the insert back —
    nothing is ever committed, so no row is orphaned and none is left
    disconnected. The caller still holds the content and the id of the current
    head, so it can rebase and retry (optimistic concurrency, 409-style). There
    is deliberately no delete and no orphan_memory_id: the atomic rollback makes
    both impossible, a stronger guarantee than the former rollback-over-orphan.
    """
````

## Original comment, lines 1024–1031

````text
# ── User-mood EMA hook (Bower 1981 mood-congruent recall, signal side) ──
# Engineering default; calibration pending future work — Bower (1981)
# "Mood and Memory" Am. Psychologist 36(2) prescribes mood-congruent
# recall qualitatively, not the time-constant of mood drift. No published
# psychophysics constant for the EMA decay of self-report mood at the
# session timescale was located (April 2026). Conservative default
# matches the structural form of other Cortex EMAs (write_gate_calibration).
# When a published value is found, replace this constant and cite.
````

## Original docstring, lines 1040–1069

````text
"""EMA-update the user's session-level mood from VADER on user content.

    Contract:
      pre:  content is a hardened, non-empty string; source is one of the
            remember.py source enum values; store exposes get_user_mood /
            set_user_mood (real PgMemoryStore or duck-compatible stub).
      post: when source == "user" AND MOOD_CONGRUENT_RERANK is NOT ablated,
            user_mood.valence is upserted to
                (1 - α) * old + α * vader_compound(content)
            with α = MOOD_EMA_ALPHA, old defaulting to 0.0 when the row
            is absent. Returns the new valence on update, or None when
            skipped (non-user source, ablated, or store missing API).
            Never raises — failures are swallowed and reported as None.

    Source-discipline notes:
      - VADER compound: Hutto & Gilbert, ICWSM 2014.
      - Mood-congruent recall: Bower 1981 Am. Psychologist 36(2).
      - α = 0.3: engineering default (see module-level comment above).

    User-side definition (self-flagged risk addressed):
      Only source == "user" updates mood. System-generated memories
      (source ∈ {"tool", "consolidation", "import"}) and conversational
      transcripts (source == "session", which is mixed agent/user)
      do NOT mutate user_mood, because their content does not reflect
      the user's affective state at recall time.

      Ablation symmetry: when CORTEX_ABLATE_MOOD_CONGRUENT_RERANK=1,
      we also skip the write so the table doesn't accumulate signal
      that's then ignored downstream (clean ablation deltas).
    """
````

## Reviewed remaining docstring (mcp_server/handlers/remember_helpers.py, interim lines 154–173)

````text
Compute all novelty signals and gate decision.

Contract:
  pre:  content is a non-empty string; embedding is either None or a
        valid vector; ``domain`` is the resolved (normalised) domain
        for this write path; ``write_class`` is the ALREADY-RESOLVED
        class from ``core.write_class.classify_write_class`` (issue
        #147) — ``""`` only for callers/tests that don't care about
        the write-class contract; production callers always pass the
        resolved value (never ``""``).
  post: the returned dict contains ``should_store``, the observed
        ``gate_reason``, and the ``gate_threshold`` actually used for
        the decision. Side effect: the per-domain calibration EMA is
        updated via ``write_gate_calibration.record`` when the decision
        was NOT a bypass (bypasses are not informative for calibration).
        A resolved ``write_class == "deliberate"`` NEVER yields
        ``should_store is False`` (contract: deliberate writes are
        never novelty-rejected; near-duplicates are still merged/
        linked/superseded by ``try_curation`` afterward).
````

## Reviewed remaining docstring (mcp_server/handlers/remember_helpers.py, interim lines 642–656)

````text
Best-effort wrapper around ``validate_memory.grade_from_content``.

    Postcondition: NEVER raises. Always returns a ``_GradeContext`` whose
    ``resolution_root_explicit`` is ``bool(directory)`` -- issue #345:
    when the caller passed no ``directory``, resolution silently fell back
    to the server process's cwd, which need not be the writer's project
    root (reproduced live on memory 4341427, 2026-08-08: 3 real paths in
    the Cortex repo graded dead because the write's cwd was the repo's
    *parent* directory). On any failure returns a fallback
    ``ProvenanceReport`` graded ``UNVERIFIABLE`` (the same "we don't know"
    default ``grade_provenance`` uses for zero extractable references) plus
    the failing exception's type name, so the caller can surface it as an
    observable tag instead of a silently absorbed enrichment.

source: ADR-0438
````

