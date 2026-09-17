---
created: 2026-09-17
kind: adr
number: 1083
status: proposed
tags: [memory-scoping, team-decisions, issue-611]
title: Separate project team decisions from global knowledge
---
# ADR-1083: Separate project team decisions from global knowledge

## Status

Proposed for owner review in issue #611. Supersedes the team-to-global
mapping in ADR-0200 and the team-decision exception in ADR-1080.

## Evidence

Issue #611 records memory 4353879 from japonais-2027 injected into
anthropic-partnership by both session hooks. `team_scope.is_team_decision`
and `global_detector.resolve_global_scope` promote deliberate decisions
under an agent context to `is_global`, which bypasses project isolation.
The intended visibility across agents therefore also crosses projects.

## Decision

A team decision is visible to every agent within its project. Persist
`is_team_decision` independently of `is_global` on both backends. Team
visibility relaxes only the agent predicate. Project visibility continues
to require the recorded project root or an ancestor, as in ADR-1080.

Reserve `is_global` for an explicit global write or a positive result from
the existing content detector. A row may carry both flags when justified
independently. No detector threshold changes are part of this correction.
The Team Decisions query applies project scope before ordering and limit.
Ordinary hook recall treats team decisions as ordinary project memories.

Reclassify legacy global rows with an idempotent, explicit operator script.
Run a dry-run first and verify a PostgreSQL custom-format backup before
applying to production. Legacy rows do not persist the reason for the
global flag. Operators can preserve IDs known to have been explicitly
global through `keep_global_ids`; otherwise evaluate the existing content
detector and clear `is_global` when it
does not confirm cross-project content, setting the team marker for a
decision with an agent context. Preserve row IDs, history and supersession.

An empty directory context is never a project wildcard. Resolve it only
from a domain with an unambiguous, verified project-directory mapping,
or an explicit owner-approved memory-ID mapping recorded in the run report.
Leave unresolved rows global and enumerate their IDs for owner review.
Do not derive project ownership by guessing from prose or path suffixes.

## Verification

Both backends must exclude a project-A team decision from project B and
include it in project A for another agent. Explicit globals remain visible
in both. A second reclassification run changes no rows. Production signal:
4353879 is absent under anthropic-partnership and present under japonais-2027;
the former's Team Decisions block contains no japonais-2027 rows.

## Consequences

Schema migrations add a default-false team flag without rewriting legacy
scope automatically. The separate data operation is inspectable and
reversible from its backup. Unresolved legacy globals remain an explicit
owner-review list. Existing explicit global semantics are preserved.
