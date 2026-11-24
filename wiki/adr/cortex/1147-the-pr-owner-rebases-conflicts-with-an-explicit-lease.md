---
created: 2026-11-24T03:44:36Z
kind: adr
number: 1147
status: accepted
tags: [ci, contract, git, review, amends-adr-1132, amends-adr-1134]
title: The PR owner rebases conflicts with an explicit lease
---
# ADR-1147: The PR owner rebases conflicts with an explicit lease

## Status

Accepted by the repository owner on 2026-11-24. Replaces the blanket ban on
forced pushes and the conflict merge in rules 3 and 4 of the CI contract as
introduced in PR #973. Replaces ADR-1132's touched-tests exception for conflict
merges and updates ADR-1134's validator integration point.

## Context

On how to integrate main into a pull request branch, the owner said:

> Non ça se fait par un rebase que l'agent opère. Jamais par une intervention humaine.

Asked « Je fais modifier le contrat pour autoriser le rebase par l'agent sur
une branche déjà poussée ? », the owner answered:

> Oui, rebase et push forcé protégé

The prior ban protected work on a branch another agent might hold. A rebase
rewrites commit IDs. Ownership limits who may publish that rewrite, and an
explicit lease makes Git reject it if the remote ref differs from the SHA read
just before rebasing. The lease compares a ref value and cannot establish
ownership. Both safeguards are required.

## Decision

1. Preserve the real-conflict trigger (`mergeable_state: dirty`). The owning
   agent fetches and rebases its own PR branch onto `origin/main` and resolves the
   conflict while preserving both sets of changes. Lag alone never triggers
   synchronization. The merge-commit procedure and the GitHub branch-update
   button and API are forbidden.
2. Read the remote SHA immediately before rebasing and confirm that it is in
   the local PR history being rebased. If a push arrived between fetch and the
   remote read, incorporate those commits and repeat the read before rebasing.
   Publish only to the owned PR branch with
   `--force-with-lease=<branch>:<remote-sha>` using that SHA. A person cannot
   perform the operation, and an agent cannot perform it on another agent's
   branch or on `main`. Bare force, implicit leases
   and forced refspecs are forbidden. On lease rejection, re-read the refs,
   verify ownership and the conflict, preserve the new commits and repeat the
   rebase and checks once. Stop if the second lease fails or ownership or the
   remote branch is lost.
3. A running review bars a push. A rewrite retains the three-review budget
   under ADR-1119 and ADR-1129. An exhausted branch continues on a new branch
   under the existing one-PR rule and owner holds, with the owner's existing
   one-review exception available.
4. Run rule 8's delivery gate and conflict-resolution tests on the rebased
   commit before publishing. For validator changes, use the validator from the
   version of main now integrated into the branch under rule 9. Publish the
   rebased head as a draft and obtain independent approval of its exact SHA
   before marking it ready under rule 10. The repository resolver still
   requires the hosted checks and current-head verdict under rule 1.

## Consequences

- The explicit lease blocks a concurrent push from being silently overwritten.
  A SHA fetched again after a refusal authorizes only a new rebase that
  incorporates the new remote state. It cannot authorize the old candidate.
- The API-only worker reports the conflict and the exact head to its
  coordinator. The Git Data API's forced ref update does not supply the required
  expected-head lease.
- The author, independent reviewer and hosted resolver each use the rewritten
  head. A prior verdict cannot make it ready or mergeable.
- Reverting the policy restores the prior instructions. It cannot restore
  already rewritten refs.
