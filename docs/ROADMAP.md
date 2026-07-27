# Roadmap

_Last updated: 2026-07-27. Covers the twelve months to 2027-07._

What Cortex intends to do next, and — just as load-bearing — what it does not
intend to do. This is direction, not a commitment: the project may miss any of
it, and will say so here rather than quietly dropping an item. Dates are
deliberately absent; the ordering is the promise.

## Where the project is today

v4.16.0, released 2026-07-24. 52 standalone MCP tools (55 with the optional
upstream integrations), 9 lifecycle hooks, 36 neuroscience-grounded mechanisms
against a 97-reference bibliography, running on a local SQLite store by
default or PostgreSQL + pgvector when configured. The OpenSSF Best Practices
**passing** badge was earned 2026-07-27.

## 1. Verification depth over feature count

The next release series adds no new mechanism families. The work is making the
existing surface provably correct rather than merely green:

- **Statement coverage to ≥80%** (74.83% at 2026-07-27, measured in CI). The
  gap is concentrated in modules whose call sites were never wired: those are
  finished — the intended caller is built — rather than deleted, and each
  arrives with contract tests. A coverage floor is then enforced in CI so the
  number cannot silently fall back.
- **Maximal practical warning strictness.** Ruff currently runs its default
  rule set and pyright runs `basic` behind a per-rule ratchet. Both tighten,
  rule by rule, with the ratchet floors only coming down.
- **Mutation testing widened** past the single demonstrated module in
  `pyproject.toml`, so the test suite is judged by mutants killed rather than
  lines executed.

## 2. Supply-chain and project-health hardening

- **OpenSSF silver, then as far toward gold as one maintainer can go.** Gold
  requires a second person for `bus_factor`, `two_person_review` and
  `contributors_unassociated`; everything else is reachable alone.
- **OpenSSF Scorecard findings closed**, starting with the pinned-dependency
  set — every action is already pinned by SHA; the remaining findings are the
  container and workflow-permission ones.
- **Signed version tags** to complement the existing Sigstore artifact
  attestations, so `git tag -v` verifies as well as `gh attestation verify`
  does today.

## 3. Ingestion beyond Claude Code sessions

The typed document seam shipped in v4.16.0 (`ParsedDocument` → normalizer →
write path) exists to be extended, not to stay at two adapters:

- **Live Confluence connector** over REST, reusing the same parser and
  provenance stamping the offline export adapter already uses — only the byte
  source and the provenance URL change.
- **Provenance-first ingestion everywhere**: every ingested page keeps source
  path and content-hash version, so re-ingesting a revised document updates
  rather than duplicates.

## 4. The research line

Two papers are drafted in-repo (`docs/arxiv-thermodynamic/`,
`docs/arxiv-context-assembly/`). The intent is to submit them, and to keep the
benchmark harness (`benchmarks/reproduce.sh`) as the reproducible artifact
behind every number the papers and the README quote. Benchmark floors stay
gated on the isolated container run, never on a live store.

## 5. Raising the bus factor

The project has one maintainer and says so in
[GOVERNANCE.md](../GOVERNANCE.md). Adding a second maintainer with repository
admin is wanted, is the single change that would most improve the project's
resilience, and is not something a roadmap can schedule unilaterally — it
depends on someone showing up and staying. Sustained reviewers are the path
in; the door is the issue tracker.

## What Cortex will not do

- **No hosted service, no cloud sync, no account.** Cortex is local-first by
  construction; a server-side store would invalidate the guarantee in
  [PRIVACY.md](../PRIVACY.md) that memory content never leaves the machine.
- **No LLM in the retrieval loop.** Retrieval stays deterministic and
  local — embeddings plus lexical signals plus a small cross-encoder — so a
  recall is reproducible and costs nothing per call.
- **No heavyweight model dependency.** The 22 MB embedding model footprint is
  a hard constraint; a gigabyte-scale model breaks the runs-on-your-machine
  promise regardless of what it would buy in accuracy.
- **No re-absorption of the visualization stack.** It lives in
  [cortex-viz](https://github.com/cdeust/cortex-viz) and reads this store
  read-only; Cortex stays a memory engine.
- **No backward-compatibility shims.** Format changes ship as one-shot
  migrations, per the standing rule in [CLAUDE.md](../CLAUDE.md).
- **No telemetry by default.** OTLP export stays opt-in behind an explicit
  environment variable, and never carries memory content.
