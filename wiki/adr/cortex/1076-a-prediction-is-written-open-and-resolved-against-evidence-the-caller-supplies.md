---
created: 2026-09-16T17:39:47Z
kind: adr
number: 1076
status: accepted
tags: [predictions, calibration, brier, issue-597]
title: A prediction is written open and resolved against evidence the caller supplies
---
# ADR-1076: A prediction is written open and resolved against evidence the caller supplies

## Status

accepted

## Context

Cortex stored what happened and never what was expected, so nothing it held could turn out wrong in a way it noticed. Two measurements from 2026-09-16 made the gap concrete: mining over the 374 transcripts under `~/.claude/projects` returned 796 procedural skills, every one at proficiency 0.5 because no session records an outcome (0 of 413 entries carry a score); and while `wiki.claim_events` carries a confidence and `ingest_findings` separates a verified finding from a hypothesis, nothing records what a claim predicts, and nothing later compares it to what was observed (issue #597).

An earlier proposal was to graft prediction records onto `ingest_findings`. Reading it settled the matter: that handler consumes another producer's run artifacts off disk in that producer's format (ADR-0410), so it cannot receive a prediction born in a Cortex session.

The owner decided two things on 2026-09-16. The outcome signal is the posted review verdict, and it must work in any repository where Cortex runs, not only in this one. The records live in a surface of their own rather than in tagged memories.

The first decision rules out Cortex fetching anything. This server has no network path to a forge, knows nothing about GitHub, and must not learn this project's own `ZETETIC-REVIEW:` convention, which its merge gate enforces but which no other repository shares.

## Decision

A `predictions` table, on both backends, holds the claim, the prediction in falsifiable terms, the test that would settle it, and the confidence its author held when writing it, plus the domain, directory and optional memory it belongs to. A row is written `open` and moves once to `resolved`, carrying what was observed, a verdict of `confirmed`, `refuted` or `abandoned`, the kind of source that settled it (`review`, `ci`, `test`, `manual`) and a reference to that source. A table CHECK refuses a resolved row without a verdict, a source kind and a reference, and the handler refuses a blank reference before the database has to.

The caller supplies the evidence and Cortex never fetches it. That is what makes the contract repository-agnostic: a host maps its own review convention onto the same four fields, and nothing in the schema names a forge or a marker.

`core/calibration.py` scores the resolved rows: the Brier score (Brier 1950), reported beside the 0.25 a constant 0.5 forecast earns so the number reads without the literature, plus the reliability breakdown per confidence band, which says how often predictions in that band actually held. An abandoned prediction is counted apart and scored nowhere: its test was never run, so it says nothing about calibration.

Three tools, registered from `tool_registry_predictions.py`: `predict`, `resolve_prediction`, `calibration`. The standalone count moves from 54 to 57, 60 with both upstream integrations.

## Consequences

Easier: a confidence can now be scored rather than asserted. `calibration` answers with a Brier score, its reference point and the per-band frequencies, for one domain or for all.

`tests_py/core/test_calibration.py` pins the scoring: a constant 0.5 scoring exactly the uninformative reference, certainty that holds scoring 0, confidence that is wrong scoring worse than 0.5, the band a full confidence falls in, and an empty input scoring absent rather than zero. `tests_py/handlers/test_prediction_records.py` drives the three tools on SQLite: a prediction written open, refusals for a missing part and for a confidence outside 0 to 1, a resolution refused for a blank reference, a prediction resolving once, an unknown id, the score over two resolved rows with one still open, and the three tools present with their annotations.

Harder: nothing yet writes predictions on its own. A session that wants calibration has to state a prediction before running its test, which is the discipline the surface exists to support, not something it can impose.

Unchanged: procedural proficiency. Feeding a session's own verdict into `mine_skills` reuses this resolution contract and is the next step, not this one.
