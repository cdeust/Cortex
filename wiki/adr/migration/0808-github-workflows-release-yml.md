---
title: "ADR-0808 — .github/workflows/release.yml rationale"
status: accepted
source: .github/workflows/release.yml
---

# ADR-0808 — .github/workflows/release.yml

Source rationale preserved verbatim. Identifiers inside historical quotations are not current identities.

## .github/workflows/release.yml — original line 3

````text
# Cortex's PRIMARY install path is Anthropic's plugin marketplace
# (`/plugin install hypermnesia-mcp@cortex-plugins`). The marketplace consumes the
# git tree directly via ``${CLAUDE_PLUGIN_ROOT}``. See ADR-0050.
````

## .github/workflows/release.yml — original line 7

````text
# PyPI is the best-effort secondary, hook-free compatibility channel for stdio
# hosts such as Gemini CLI and Codex CLI. Claude's marketplace remains primary.
# The publish-pypi job below is intentionally non-blocking with respect to the
# GitHub Release and marketplace propagation: a PyPI rejection (for example,
# a removed Trusted Publisher entry) must be repaired, but must not suppress
# those primary artifacts. Publishing uses PEP 740 Trusted Publishing (OIDC)
# against the trusted-publisher entry configured for this workflow + environment
# `pypi` — the same one that published versions up to 3.14.7.
````

## .github/workflows/release.yml — original line 16

````text
# THIS WORKFLOW DOES NOT TEST ANYTHING (issue #392). Before this change it
# ran its own `test` job on tag push — a duplicate, differently-triggered
# copy of ci.yml's gate that every CI hardening pass silently skipped
# (ci.yml triggers on `push: branches` + `pull_request`, this workflow on
# `push: tags`, so a tag never reached it). Release run 30741657854
# (v4.17.0) is what that cost: a reranker-fetch hang that ci.yml's own
# hardening had already fixed hung this file's copy anyway, blocking every
# downstream publish job on a tag whose tree had just passed 20 green
# checks on PR #334.
````

## .github/workflows/release.yml — original line 26

````text
# The test guarantee now comes from `ci.yml`'s `release-gate` job: it runs
# ONLY after `ci-green` succeeds on a push to `main`, and tags the EXACT SHA
# that just went green with an annotated `git tag` pushed via
# `RELEASE_TAG_TOKEN` (a `GITHUB_TOKEN`-pushed tag does not start a new
# workflow run, per GitHub's docs — this workflow would never fire from
# one). The released tree is therefore bit-identical to the validated one;
# this workflow's only job is to propagate what `ci.yml` already validated
# and tagged — creating a GitHub Release with auto-generated notes, and
# attempting the secondary PyPI compatibility channel.
# `requirements/release.txt` — the dependency set the deprecated PyPI
# channel installs into — is still validated: `ci.yml`'s `release-deps` job
# smoke-imports the server under it on every push and PR.
````

## .github/workflows/release.yml — original line 39

````text
# Supply-chain hardening (issue #178). Cortex reads and persists every
# session transcript and installs session hooks with the user's full
# filesystem access; a substituted wheel is a keylogger on the user's
# work, and until now the wheel shipped with nothing a user could verify.
# This workflow now:
#   * attests build provenance for the wheel, the sdist and the SBOM
#     (Sigstore-backed; verify with `gh attestation verify <file>
#     --repo cdeust/Cortex`);
#   * publishes a CycloneDX SBOM generated from uv.lock, so the ML stack
#     (torch/transformers/scipy/scikit-learn) — the bulk of the attack
#     surface — is enumerable rather than opaque;
#   * publishes a `<asset>.sha256` companion for every GitHub Release
#     asset, verified on download by scripts/verify_release_artifact.py;
#   * pins every third-party action to a commit SHA (a floating tag in the
#     job that builds and signs releases is a live supply-chain hole).
# PyPI keeps PEP 740 attestations (native to Trusted Publishing) in
# addition to the GitHub attestations above.
````

## .github/workflows/release.yml — original line 57

````text
# workflow_dispatch (issue #246) exists ONLY to verify the pinned actions
# (checkout/cache/upload-artifact/download-artifact) on a real run without
# shipping a real release: this workflow is tag-triggered only, so no PR
# CI ever exercises the build → upload-artifact → download-artifact round
# trip, and the round trip changed shape across actions/artifact v2 → v4
# (see the "Why release.yml was not done blind" note in issue #246). Every
# step that would create a GitHub Release, attach assets to one, or publish
# to PyPI is gated `if: github.event_name == 'push'` so a manual dispatch
# exercises the Node24 action bump only — it never mutates a release.
````

## .github/workflows/release.yml — original line 67

````text
# This workflow deliberately stays TAG-TRIGGERED and NON-REUSABLE: PyPI
# Trusted Publishing does not support reusable workflows, and this repo's
# publisher entry is keyed on (release.yml, environment=pypi) specifically
# — a `workflow_call` conversion would silently break `publish-pypi`,
# silently because it carries `continue-on-error: true`.
````

## .github/workflows/release.yml — original line 79

````text
# Least privilege at the top level; jobs that mint OIDC tokens widen it
# locally (issue #178). `contents: write` is the release-upload scope.
````

## .github/workflows/release.yml — original line 87

````text
# Real releases only (issues #246 + #247 criterion 5) — a
# workflow_dispatch verification run must never create a GitHub Release.
# `startsWith(github.ref, 'refs/tags/')` alongside `event_name == 'push'`
# (boy-scout fix, issue #392): this job previously gated on event_name
# alone while its softprops/action-gh-release step below carries no
# `tag_name:` and falls back to `GITHUB_REF` — a push to a BRANCH would
# therefore have created (or updated) a "release" named after that
# branch. Every other job in this file already required the tag-ref
# form; this one was the exception.
````

## .github/workflows/release.yml — original line 98

````text
# source: run 32889444672 (2026-08-25), max 39s; ceil(2 * 39 / 60).
````

## .github/workflows/release.yml — original line 126

````text
# ── Best-effort hook-free PyPI compatibility channel ──────────────────
# Restored after being dropped in a2dc7e3. Marketplace (ADR-0050) is the
# primary path; these jobs provide the hook-free `pip install` / `uvx`
# compatibility path. Decoupled from github-release so a PyPI failure never
# blocks the primary channel; docs therefore label this path best-effort.
````

## .github/workflows/release.yml — original line 133

````text
# Only the real tag-triggered event ships a release artifact; a
# workflow_dispatch verification run (issue #247 criterion 5) builds
# nothing — every job in this file is independent now that `test` (the
# thing they all used to wait on) is gone (issue #392).
````

## .github/workflows/release.yml — original line 139

````text
# source: run 33725153709 (2026-09-03), max 31s; ceil(2 * 31 / 60).
````

## .github/workflows/release.yml — original line 154

````text
# --no-deps: the file is the complete, uv-resolved dependency graph
# — pip must install it as-is rather than re-deriving it from
# metadata (see ci.yml's "Install dependencies" steps for why:
# pyproject.toml's [tool.uv] override-dependencies is a uv-only
# mechanism the exported requirements.txt format cannot carry).
````

## .github/workflows/release.yml — original line 164

````text
# Checksums for every artifact BEFORE attestation and upload, so the
# `<asset>.sha256` a user verifies with scripts/verify_release_artifact.py
# describes exactly the bytes that were attested (issue #178 criterion 4).
````

## .github/workflows/release.yml — original line 190

````text
# Only the distributions go to PyPI; the .sha256 companions are
# GitHub-release assets, excluded here so twine sees a clean dist/.
````

## .github/workflows/release.yml — original line 197

````text
# Real releases only (issue #246) — softprops/action-gh-release
# creates the tag_name release if it is absent, which would forge
# a release out of a workflow_dispatch verification run.
````

## .github/workflows/release.yml — original line 210

````text
# CycloneDX SBOM for the FULL dependency graph (issue #178 criterion 3).
# Generated from uv.lock via `uv export`, so it lists the exact versions the
# release resolves to — including torch/transformers/scipy/scikit-learn,
# which arrive transitively through sentence-transformers and are the bulk
# of the attack surface. Deriving it from the lock (not a live install)
# keeps the job bounded and reproducible: "what is in this distribution" is
# answered from the same lock the wheel is built against, and the several-
# hundred-MB torch download is not on the critical path.
````

## .github/workflows/release.yml — original line 220

````text
# Only the real tag-triggered event ships an SBOM to a release; a
# workflow_dispatch verification run (issue #247 criterion 5) builds
# nothing (see `build`'s identical comment for why there is no `needs:`).
````

## .github/workflows/release.yml — original line 225

````text
# source: run 32889444672 (2026-08-25), max 32s; ceil(2 * 32 / 60).
````

## .github/workflows/release.yml — original line 269

````text
# Real releases only (issue #246) — same forged-release hazard as
# the build job's attach step.
````

## .github/workflows/release.yml — original line 280

````text
# MCPB connector bundle (Claude Desktop / Cowork drag-and-drop install).
# manifest.json + .mcpbignore already described a valid MCPB 0.4 bundle, but
# nothing built it: v4.14.3 through v4.16.0 shipped zero release assets, so
# the only way to get this bundle was to clone the repo and pack it by hand.
````

## .github/workflows/release.yml — original line 285

````text
# The bundle carries source + manifest only — `uv run` resolves dependencies
# from the bundled pyproject.toml/uv.lock at launch — which is why it is
# 2.1MB and not the ~700MB an installed tree would be.
# source: measured 2026-08-01 on the v4.17.0 tree — 2.1MB package /
#   5.8MB unpacked / 561 files / 222 ignored by .mcpbignore.
````

## .github/workflows/release.yml — original line 292

````text
# Only the real tag-triggered event ships a bundle; a workflow_dispatch
# verification run (issue #247 criterion 5) builds nothing (see `build`'s
# identical comment for why there is no `needs:`).
````

## .github/workflows/release.yml — original line 297

````text
# source: run 32889444672 (2026-08-25), max 25s; ceil(2 * 25 / 60).
````

## .github/workflows/release.yml — original line 311

````text
# `npm ci` against the committed lockfile, not `npx @anthropic-ai/mcpb@x`:
# an exact version is not a pin (§ hash-pinned installs, issue #203) —
# only the lockfile's sha512 integrity entries pin the bytes. The
# lockfile also carries a `tmp` override, because the CLI's transitive
# @inquirer/prompts -> external-editor -> tmp chain resolves to a version
# inside the GHSA-52f5-9888-hmc6 / GHSA-ph9p-34f9-6g65 range by default.
````

## .github/workflows/release.yml — original line 380

````text
# Provenance BEFORE upload, same ordering and rationale as the wheel/sdist
# and SBOM jobs: the attestation binds the digest a user verifies with
#   gh attestation verify <bundle> --repo cdeust/Cortex
````

## .github/workflows/release.yml — original line 389

````text
# Real releases only (issue #246) — same forged-release hazard as the
# build and sbom jobs' attach steps.
````

## .github/workflows/release.yml — original line 404

````text
# `build` already skips on a non-tag run (which also skips this job by
# GitHub's default needs-skip propagation); stated explicitly so the
# tag-only contract survives a future edit to `build`'s condition.
````

## .github/workflows/release.yml — original line 409

````text
# source: run 33809450915 (2026-09-03), max 23s; ceil(2 * 23 / 60).
````

## .github/workflows/release.yml — original line 427

````text
# Real releases only (issue #246). The download-artifact step above
# stays unconditional: it is the half of the upload/download round
# trip a workflow_dispatch run exists to verify (AC3); only the
# actual publish — which would push a real package version — is
# gated to a real tag push.
````

## .github/workflows/release.yml — original line 440

````text
# PEP 740 attestations are ON by default here (id-token: write is
# present); the package page shows a verified build alongside the
# GitHub attestations minted in the build job.
````

## .github/workflows/release.yml — original line 444

````text
# skip-existing so a retag against an already-published version
# is a no-op instead of a hard failure — this was the exact
# failure mode that motivated removing PyPI in a2dc7e3.
````

## .github/workflows/release.yml — original line 449

````text
# Public MCP registry (registry.modelcontextprotocol.io) compatibility
# channel — a THIRD version surface alongside the marketplace pin and
# PyPI, previously updated by hand and, like the other two, drifting
# silently: `io.github.cdeust/hypermnesia-mcp` sat published at 4.17.1
# while this repo's tag, server.json, and PyPI were already at 4.17.2 —
# one release short, invisible until queried directly (no CI gate read
# this surface until scripts/check_marketplace_pins.py's
# REGISTRY_VERSION_STALE check, added alongside this job). Same failure
# shape as issue #179 (marketplace pin) and the cortex-viz CHANGELOG
# incident: a mandatory per-release step that lived only in prose.
````

## .github/workflows/release.yml — original line 460

````text
# Auth: GitHub OIDC (`mcp-publisher login github-oidc`), NOT a
# PyPI-Trusted-Publishing equivalent — a distinct mechanism documented at
# modelcontextprotocol/registry docs/reference/cli/commands.md and
# docs/modelcontextprotocol-io/github-actions.mdx (checked 2026-08-10,
# not assumed). `io.github.cdeust/*` namespace authentication comes free
# from the workflow's own OIDC token (bound to this repo + workflow +
# ref by Sigstore) once `id-token: write` is granted — no stored secret,
# unlike the PAT or DNS auth alternatives the docs also describe.
````

## .github/workflows/release.yml — original line 470

````text
# `needs: publish-pypi`, NOT `build` — the registry's package-ownership
# verification (see server.json's `packages[].registryType: pypi`)
# resolves the version this job's `server.json` declares against what
# PyPI actually serves. `build` only builds the sdist/wheel; the PyPI
# publish itself happens in `publish-pypi`, a job that runs in
# parallel with this one when both only `need: build` — so a fast
# registry publish could name a version PyPI had not yet received,
# the exact "dangling pin, in reverse" shape this PR's own
# REGISTRY_VERSION_STALE check exists to catch (cortex-viz's own
# Release.yaml gates its registry job on `needs: [test, release]` for
# the identical reason — verified against that workflow, not assumed).
````

## .github/workflows/release.yml — original line 484

````text
# source: run 32889444672 (2026-08-25), max 14s; ceil(2 * 14 / 60).
````

## .github/workflows/release.yml — original line 501

````text
# Checksum-verified, not just version-pinned (issue #178 supply-chain
# posture applied to a third-party tool this workflow now trusts).
# source: sha256 measured 2026-08-10 by downloading this exact asset
# from https://github.com/modelcontextprotocol/registry/releases/tag/v1.8.1
````

## .github/workflows/release.yml — original line 520

````text
# Same rationale as publish-pypi: this is a secondary compatibility
# channel (ADR-0050 names the marketplace primary) — a registry
# outage or a stricter future validation rule must not red-X the
# GitHub Release / marketplace propagation this workflow exists to
# ship. A silenced failure is exactly what let this surface drift
# in the first place, so it is not swallowed: the step still shows
# red in the Actions UI, `continue-on-error` only stops it from
# failing the *job*/workflow.
````

## .github/workflows/release.yml:jobs.github-release.steps.1.run — original line 1

````text
# Get previous tag
````

## .github/workflows/release.yml:jobs.github-release.steps.1.run — original line 8

````text
# Write to file to avoid escaping issues
````

## .github/workflows/release.yml:jobs.sbom.steps.3.run — original line 2

````text
# Full transitive graph, all extras, pinned to uv.lock. --no-emit-project
# drops the local package's own editable line so cyclonedx sees only
# third-party components. --no-hashes because cyclonedx-py records the
# component set, not the wheel hashes (those live in the .sha256 files).
````

## .github/workflows/release.yml:jobs.mcpb-bundle.steps.4.run — original line 26

````text
# ensure_ascii=False so the description's em-dash stays a literal
# character instead of a — escape, matching committed server.json.
````

## Final non-Python residual audit

### .github/workflows/release.yml — pre-cleanup line 255

````text
          # Fail loudly if the ML stack is somehow absent — criterion 3 names it.
````

### .github/workflows/release.yml — pre-cleanup line 325

````text
          # The tag must describe the tree it is built from, or a user installing
          # the asset gets a version the release notes do not describe.
````

### .github/workflows/release.yml — pre-cleanup line 338

````text
      # The MCP registry's `mcpb` registryType requires the artifact's URL and
      # its sha256 — neither of which exists until the bundle is built and its
      # download URL is known. The committed server.json therefore keeps the
      # pypi package (its identifier is version-addressable, not URL-addressed)
      # and this step emits the resolved variant carrying BOTH packages, as a
      # release asset to submit to the registry.
````

### .github/workflows/release.yml — pre-cleanup line 411

````text
    # OIDC Trusted Publishing — no stored secret. Verified by PyPI against
    # the trusted-publisher entry for (cdeust/Cortex, release.yml,
    # environment=pypi). This is the same entry that published <= 3.14.7.
````

### .github/workflows/release.yml — pre-cleanup line 434

````text
        # Best-effort channel: a rejected upload (already-exists, or the
        # Trusted Publisher entry was removed) must NOT red-X the primary
        # marketplace/GitHub release.
````
