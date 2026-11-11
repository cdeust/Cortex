---
created: 2026-11-11T09:00:00Z
kind: adr
number: 1131
status: accepted
tags: [ci, resolver, merge, dependabot, risk-tier, fleet, amends-adr-1126]
title: The resolver reads the low-risk file names from ci.json
---
# ADR-1131: The resolver reads the low-risk file names from ci.json

## Status

accepted. Amends ADR-1126 (a Dependabot minor or patch update of the dependency files merges without a review): the file names leave the workflow.

## Context

Owner decision 2026-11-10: the CI of every repository of the fleet is identical to Cortex's, and Cortex's copy is the source. `pipeline-post-merge.yml` could not be copied as it was. Its resolver held `LOW_RISK_FILES = {"uv.lock", "pyproject.toml"}`, the files of Cortex's uv ecosystem, and each sibling had rewritten that one constant for its own (ai-architect-mcp-spec: `pnpm-lock.yaml`, `package.json`; zetetic-team-subagents: nine names). The siblings had also added two rules Cortex lacked: a file is matched by its name in any directory, because a workspace carries one manifest per package, and a path under `.github/` is never low risk.

The names of the required jobs and of the workflows (`contract`, `unit`, `regression`, `e2e`, `merge`, the `environment` and `install` matrices, `Pipeline`, `PR Review`) do not differ: the resolvers of ai-architect-mcp-codebase, ai-architect-mcp-spec, ci-autonome, claude-mods, cortex-viz and zetetic-team-subagents differed from Cortex's only in the low-risk lines (compared on 2026-11-11). They stay in the workflow.

## Decision

1. `ci.json` gains a required key, `low_risk_files`: a list of file names without a directory. Cortex's value is `["uv.lock", "pyproject.toml"]`, the files ADR-1126 named. An empty list is valid and means no dependency update skips the review.
2. The resolver reads `ci.json` from the default branch through the contents API, with no `ref`, so a pull request cannot change its own tier (ADR-1126, point 4). It reads it only for a pull request opened by `dependabot[bot]`.
3. A missing file, a missing key or a malformed list fails the resolver run. No list is built in.
4. A changed file is matched by its file name, and a pull request that touches a path under `.github/` is not low risk whatever the name.
5. The `ci.json` validator embedded in the `contract` job of `pipeline.yml` and `pipeline-post-merge.yml` accepts the key and reports its absence, so a repository without it fails on its pull request, before the resolver ever runs. The validator therefore differs from `tools/ci_contract.py` of zetetic-team-subagents, which refuses the key as unknown.

## Consequences

Positive: the resolver holds no repository's file names, so `pipeline-post-merge.yml` and `pipeline.yml` can be the same bytes in every repository; what differs is in `ci.json`, which already held what differs.

Negative: a repository that takes these files must add `low_risk_files` to its `ci.json` in the same pull request, or its `contract` job fails. In Cortex a `pyproject.toml` or `uv.lock` in a subdirectory now counts as a dependency file; the tracked tree has only the two at the root. The resolver makes one more API call per Dependabot pull request.

Not done here: the two files still name things only Cortex has (the step that runs `scripts/tests/test_no_main_comparison.py`, the `npm ci --prefix .github/claude-cli` install), and their header still says they are rendered from the zetetic-team-subagents template. A repository that takes them needs those files too.

Tests: `tests_py/scripts/test_ci_low_risk_files_from_ci_json.py` (the names come from the default branch's `ci.json`; another repository's list decides; the resolver source names no dependency file; a missing key, a malformed list or an unreadable file fails; matching by file name; `.github/` excluded; the validator requires the key and both workflows embed the same validator). `tests_py/scripts/test_ci_low_risk_tier.py` now feeds the resolver this repository's `ci.json` list.

## Alternatives considered

- One list in the workflow with every ecosystem's names (what zetetic-team-subagents carries): rejected, a repository would accept manifests of ecosystems it does not declare, and each new ecosystem would edit every repository's workflow.
- Reading `ci.json` from the head of the pull request: rejected, the tier must come from a file the pull request cannot change.
- Moving the required job names to `ci.json` as well: rejected, they do not differ between repositories, and a key there would let a repository weaken its own merge gate.
