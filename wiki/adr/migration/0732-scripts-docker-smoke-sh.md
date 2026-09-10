# ADR-0732: scripts/docker_smoke.sh implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `scripts/docker_smoke.sh`; original SHA-256 `8e5092da61ae402ad035c84e5c1d8ceacf1e665321d224c65223da6630dc760a`.

## Original shell-comment, lines 2–28

````text
# Bare-container / DB-less MCP contract smoke test.
#
# Guards the regression fixed on fix/bare-container-contract (H4 root cause,
# see commit 5d71069c): third-party registry indexers (Glama et al.) run
# `docker build` from the bare repo, then `docker run --rm -i` with ZERO env
# vars and ZERO external services, and expect `tools/list` to answer with the
# standalone tool set. That contract silently broke for two months because
# nothing in CI exercised it — every CI job installs the `[postgresql]` extra
# and/or starts a database, so the "psycopg absent, no DB" path was never hit.
#
# This script builds the production image from the repo root Dockerfile, then
# delegates the run+exchange+assert sequence to `scripts/docker_smoke_client.py`
# (see that module's docstring for why: the stdio exchange with the container
# must keep stdin open until every expected response has arrived, which bash
# `printf | docker run` cannot do — it closes the container's stdin the
# instant the batch is written, which is what made this gate intermittent
# rather than simply broken; commit 18d4505 documents the interleaving, PR
# #331 fixed the identical defect for a local subprocess via
# `scripts/mcp_host_client.py`, and this script now reuses that fix).
#
# Usage:
#   scripts/docker_smoke.sh                  # build image + smoke test
#   scripts/docker_smoke.sh --skip-build      # reuse an already-built image
#   CORTEX_SMOKE_IMAGE=cortex:latest scripts/docker_smoke.sh --skip-build
#
# Exit code: 0 on success, non-zero (with a diagnostic on stderr) on failure.
# Used by both CI (.github/workflows/ci.yml, job `docker-smoke`) and local dev.

````

## Original shell-comment, lines 32–42

````text
# source: tests_py/test_main.py::TestMain::test_standalone_baseline_is_52_tools
# — the 52 standalone tools registered with zero upstream MCP servers
# reachable (codebase=False, prd=False): 49 re-derived 2026-07-12 via a live
# `docker run` + `uv run hypermnesia-mcp` round-trip (fix/bare-container-
# contract root-cause report), + `wiki_migrate` (FS→PG wiki parity), +
# `check_setup` (issue #115), + `ingest_document` (issue #192). Boy-scout
# fix 2026-07-30: this was still 49, citing a test name
# (test_standalone_baseline_is_49_tools) that no longer exists — the gate's
# floor was silently weaker than the true baseline for three tools' worth
# of regression headroom. `>=` guards against future regression without
# requiring an edit here every time a tool is added.

````

## Original shell-comment, lines 48–52

````text
# source: DOCKER_RUN_TIMEOUT_SECONDS below is not new — it is the same
# budget this script has used for its `docker run` watchdog since the
# watchdog was introduced (measured 2026-07-30 against a deliberately
# hanging test image; see `scripts/docker_smoke_client.py`'s docstring for
# the kill-mechanism rationale, which the watchdog now implements).

````


## Final non-Python residual audit

### scripts/docker_smoke.sh — pre-cleanup line 30

````text
# `exec` replaces this shell with the Python driver: the driver's exit code
# becomes this script's exit code, and there is no shell-level stdio piping
# left for a race to hide in.
````
