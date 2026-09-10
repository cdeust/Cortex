# ADR-0442: mcp_server/handlers/remember_schema.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/handlers/remember_schema.py`; original SHA-256 `5039559f472e3f963be098ec8fbd7dd9ed4309905193380c23d942cf70dda9e2`.

## Original comment, lines 208–218

````text
# source:
                # mcp_server/core/distillation_reporting.py::build_distill_prompt
                # is the sole emitter of source='distillation' (grep-verified,
                # 2026-07-12) — the required-call-shape prompt for M-D8
                # distillation dossiers. classify_write_class (core/write_class.py)
                # does not special-case it (not in _DERIVED_SOURCES/
                # _MECHANICAL_SOURCES prefixes/sets), so an unclassified
                # 'distillation' source falls through to DELIBERATE by default —
                # matching the prompt's own explicit write_class='deliberate'.
                # Safe to enumerate: no downstream `source ==`/`source in`
                # branch treats it specially (grep-verified).
````

## Original schema description, interim lines 223–233

````text
Name of the tool whose output produced this content, for automatic capture paths (issue #365). Resolves the capture ORIGIN out-of-band, from the channel rather than the text: content produced by a network tool (WebFetch/WebSearch) may NOT claim the content-derived write-gate bypasses, so a fetched page cannot install itself in long-term memory by looking like a decision or an error. Distinct from 'source' (which pipeline wrote this) and from the provenance grade (whether the content's references check out). Omit for deliberate user writes.
````

## Original schema description, interim lines 240–265

````text
Explicit write class — the caller states what kind of write this is; no source-string inference happens when this is set (M-D2). One of: 'auto' (unattended tool-output capture — subject to the standard novelty gate AND homeostatic heat regulation; this is the ONLY class ever folded/re-suppressed toward the domain heat target); 'deliberate' (a considered, user- or agent-authored fact, decision, or lesson — NEVER rejected by the gate for low novelty and NEVER heat-folded; near-duplicates are still merged/linked/superseded by curation, so redundancy is handled without risking silent loss of a considered write); 'derived' (machine-synthesized from an existing corpus — consolidation/memify, CLS semantic promotion, sleep-compute auto-narration — judged by idempotence markers instead of the novelty gate); 'mechanical' (one-shot bulk import or structural indexing — backfill, ingest_*, seed_*, codebase_analyze, wiki pointer sync — bypasses the gate entirely, force=true semantics). Omit to default to 'deliberate' via source-based fallback classification (safe default — an unclassified write is never assumed to be noise). An unrecognized value is rejected with a ValidationError, never silently reinterpreted.
````

## Original schema description, interim lines 325–330

````text
Initial heat override [0.0, 1.0] used by backfill and import paths to reflect historical memory age. Defaults to 1.0 for live writes. Surprise boost still applies on top. Setting this below 1.0 keeps old memories out of the hot cohort so homeostatic scaling can rebalance the distribution (issue #14 P1).
````

