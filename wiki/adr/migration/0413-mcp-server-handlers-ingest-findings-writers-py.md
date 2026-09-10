# ADR-0413: mcp_server/handlers/ingest_findings_writers.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/handlers/ingest_findings_writers.py`; original SHA-256 `5c2fb808fcfd7aa4f67bd12df1e967b9c5b4f5a110e31d69e4d83761941b5525`.

## Original docstring, lines 1–27

````text
"""Writes one FindingRecord into Cortex's store (INC5.1 design D2-D4).

Gradation (D2): verified finding -> memory(tags: finding,verified) + wiki
page (draft, published like ingest_prd) + page_sources(link_kind='finding',
code files the finding is ABOUT) + page_sources(link_kind='extracted_from',
the document the finding was extracted FROM, when stage-1's source_path is
present) + one wiki.memos row per receipt. Unverified finding -> memory
only (tags: finding,hypothesis), low confidence, no page — a hypothesis is
not documentation.

Pipeline convention (5.1b): run stage-4 (``prepare_prd_input``) for a
verified finding BEFORE calling ``ingest_findings`` if you want code
anchoring (link_kind='finding') in the resulting wiki page — without it,
``file_paths`` is empty (not guessed). This is independent of
``source_path`` (link_kind='extracted_from'), which comes from stage-1
and needs no extra step.

Idempotence (D2 acceptance criterion, risk 8): every write here is keyed
by (run_id, finding_id[, stage]) and checked for existence before insert,
so re-ingesting the same run produces the same row counts. ``upsert_page``
and ``upsert_page_sources`` are already idempotent by construction
(ADR-0051); the memory and memo writers add their own existence checks
because ``insert_memory``/``insert_memo`` have no ON CONFLICT clause.

Composition-root-adjacent: called by ingest_findings.handler() once per
finding. Touches MemoryStore + the wiki PG schema + the wiki filesystem.
"""
````

## Original comment, lines 43–50

````text
# Distinct from _FINDING_LINK_KIND ('finding' = code files the finding is
# ABOUT, from stage-4 matched_symbols). 'extracted_from' = the document
# the finding was EXTRACTED FROM (stage-1 ExtractedFinding.source_path,
# an absolute filesystem path to a source document, not project-relative
# code — see ingest_findings_artifacts.FindingRecord docstring). Kept as
# a separate link_kind, not folded into 'finding', so a graph reader can
# tell "provenance of the finding" apart from "subject matter of the
# finding" without inspecting confidence/source metadata.
````

## Original comment, lines 120–122

````text
# M-D2 (7.4): bulk ingestion from the AP pipeline — bypasses the
        # `remember` gate entirely (direct insert_memory), same rationale
        # as ingest_codebase/seed_project.
````

