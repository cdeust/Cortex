# Security Policy

## What Cortex accesses

Cortex runs with your user's full permissions and, by design, reaches the
most sensitive parts of your engineering environment. Stated plainly so the
assurance below can be judged against the actual exposure:

- **Every Claude Code session transcript** under `~/.claude/` — it reads and
  persists conversation history (`projects/*/**.jsonl`), memory notes and
  session logs to build your memory store (see `PRIVACY.md`).
- **Session hooks** — it installs `SessionStart` / `SessionEnd` /
  `PostToolUse` hooks (`hooks/`, `scripts/install_hooks.py`) that execute
  automatically on Claude Code lifecycle events.
- **Your filesystem**, at your user's permission level — it reads source
  trees you point it at and writes its store and agent-config files.

A substituted or tampered Cortex distribution is therefore a keylogger on
your engineering work. That is precisely why the artifact integrity story
below exists: the local-only privacy guarantee in `PRIVACY.md` is only as
strong as the guarantee that the code you ran is the code we published.

## Supply-chain assurance

As of issue #178, every Cortex release ships with verifiable provenance
(`.github/workflows/release.yml`):

- **Build provenance** — the wheel, the sdist and the SBOM each carry a
  Sigstore-backed [build-provenance attestation](https://docs.github.com/actions/security-guides/using-artifact-attestations).
  Verify a downloaded asset binds to this repository and workflow:

  ```bash
  gh attestation verify hypermnesia_mcp-<version>-py3-none-any.whl \
    --repo cdeust/Cortex
  ```

- **PyPI provenance** — the deprecated PyPI channel publishes via PEP 740
  Trusted Publishing with attestations, so the package page shows a verified
  build. (`pip` verifies distributions against PyPI's recorded hashes; this
  adds *who built it and from which commit* on top.)

- **SBOM** — a CycloneDX SBOM (`hypermnesia-mcp.cdx.json`) generated from
  `uv.lock` accompanies every release, enumerating the full transitive
  dependency graph including the ML stack (torch / transformers / scipy /
  scikit-learn) that is the bulk of the attack surface.

- **Checksums** — every GitHub Release asset has a `<asset>.sha256`
  companion. Verify a download before trusting it:

  ```bash
  python scripts/verify_release_artifact.py <asset> --checksum-file <asset>.sha256
  ```

  A mismatch exits non-zero and prints both digests; this is the consumer
  side of the checksums, and it is what closes the risk — an attestation
  nobody checks changes nothing.

- **Continuous analysis** — CodeQL runs on a schedule via GitHub's default
  code-scanning setup (Python, JavaScript/TypeScript and Actions), and OpenSSF
  Scorecard via `scorecard.yml`. The Scorecard number is a recorded baseline,
  not a badge.

- Change control: `main` requires the `merge` check from GitHub Actions and
  `CodeQL` from GitHub's code-scanning app. The aggregate Pipeline gate checks
  contract, unit, regression and end-to-end tests, environment/install checks
  on Linux, macOS and Windows, and native Codex review evidence for the current
  head. Claude's requirement follows `CLAUDE_REVIEW_GATE` in the default-branch
  `.github/workflows/claude.yml`. These branch protections apply to administrators;
  force pushes and branch deletion are disabled. The observed configuration is
  recorded in `docs/verification/claude-bot-ci-20261027.md`.

### Automated review evidence

Codex and Claude use their own GitHub App identities for review publication.
Their respective gates validate evidence for the exact pull-request head.
Claude publishes `COMMENT` reviews; these are not GitHub `APPROVE` reviews.
Human approval is not required by the current branch configuration.

When a completed native security review has a nullable unresolved-findings
verdict, the gate requires a nonempty, complete match between its announced
findings and authenticated GitHub review threads. Every matching finding must
be resolved through the repository owner account. Authorized automation uses
that account to resolve verified findings. A contributor resolving their own
conversation does not satisfy this proof. Explicit native verdicts retain
their existing validation.

**What this does NOT claim.** Provenance proves *who built the artifact and
from which commit*, not that the source is free of defects; and it is worth
nothing to a user who does not run the verification commands above. The
supported marketplace install path consumes the git tree directly
(ADR-0050), so its integrity is the tagged commit plus its attestation, not
a downloaded checksum. The container image built in CI is a bare-container
*smoke test* (`ci.yml`, `docker-smoke`) — it is never pushed to a registry,
so there is no published image to attest.

### Dismissed CodeQL alerts

An alert is dismissed here only when the dismissal is *checkable* — the
paragraph must state which value CodeQL believed was sensitive and where that
value is defined, so a reader can refute the dismissal without rerunning the
scanner. Anything else stays open.

- **#143 — `py/clear-text-storage-sensitive-data`, high severity**
  (`benchmarks/lib/trust_factor_sweep.py:179`, PR #399). Dismissed as a false
  positive. The alert names its own two sources: the frozenset at
  `mcp_server/core/capture_origin.py:131-133` and the `trusted_origins_at_read()`
  call at `benchmarks/lib/trust_factor_sweep.py:174`. Their value is the triple
  of public string literals `("deliberate", "legacy", "local_action")`, defined
  at `capture_origin.py:66-70` — the read-time trust allowlist of issue #368,
  not a credential. It is written to a benchmark artefact that records which
  origin policy the sweep ran under, which is provenance, not disclosure. The
  classification is driven by the identifiers carrying the word *trusted*, and
  CodeQL itself classifies the alert as `test`. Nothing was renamed to satisfy
  the scanner: tuning production identifiers to a name heuristic would trade a
  real signal for silence. Re-open trigger: any change that makes a
  `trusted_origins*` value non-constant or reader-supplied.

## Reporting a Vulnerability

If you discover a security issue in this project, **do not** open a public
issue. Instead, send a private report to the maintainer.

**Disclosure channel:** open a [private security advisory on GitHub](https://github.com/cdeust/Cortex/security/advisories/new).

Include:

- Affected version (or commit SHA)
- Reproduction steps or proof of concept
- Impact assessment (what does an exploit accomplish?)
- Suggested fix, if you have one

## Response SLA

| Severity | First response | Patch / mitigation |
|---|---|---|
| Critical (RCE, data exfiltration, auth bypass) | 24 hours | 7 days |
| High | 3 days | 14 days |
| Medium / Low | 7 days | Best effort |

## Supported Versions

Only the latest minor release on `main` receives security patches.

## Disclosure Timeline

1. Reporter sends private advisory.
2. Maintainer acknowledges receipt within the first-response SLA.
3. Maintainer + reporter agree on a coordinated disclosure date (default
   30 days from the patched release).
4. Patched release ships; reporter is credited unless they prefer
   anonymity.
5. Public advisory published on the agreed date.

## Out of Scope

- Vulnerabilities in third-party dependencies that have not been patched
  upstream — please report those upstream first.
- Issues that require an attacker to already have control of the host
  process (in-process supply-chain attacks).
- Self-inflicted misconfigurations of your own MCP server registration.

## Recognition

Reporters who follow this disclosure process are credited in the release
notes for the patched version, unless they explicitly request anonymity.
