---
title: "ADR-0805 — .github/workflows/marketplace-pins.yml rationale"
status: accepted
source: .github/workflows/marketplace-pins.yml
---

# ADR-0805 — .github/workflows/marketplace-pins.yml

Source rationale preserved verbatim. Identifiers inside historical quotations are not current identities.

## .github/workflows/marketplace-pins.yml — original line 3

````text
# Issue #179: releasing a downstream plugin does not ship it — delivery is
# gated by the version pinned in .claude-plugin/marketplace.json. Six
# zetetic-team-subagents releases and two cortex-viz releases went out
# unpublished with no signal. This workflow makes a stale pin a red run.
````

## .github/workflows/marketplace-pins.yml — original line 33

````text
# source: run 33723724819 (2026-09-03), max 13s; ceil(2 * 13 / 60).
````

## Final non-Python residual audit

### .github/workflows/marketplace-pins.yml — pre-cleanup line 8

````text
# Cron matters more than the PR trigger: pins go stale by INACTION, and
# inaction never opens a PR. Weekly is bounded staleness (max 7 days),
# vs unbounded before.
````
