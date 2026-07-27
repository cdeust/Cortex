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

- **Change control** — `main` is protected: direct pushes are refused, every
  change lands through a pull request, and eleven status checks are *required*
  to pass before merge (`Lint`, `Type Check`, `Build Package`, `CodeQL`,
  `Docker Smoke`, `Test` on Python 3.10–3.13, `Test (SQLite backend)`, and
  `Test (Windows, SQLite backend)`). Force-pushes and branch deletion are
  blocked, and conversation resolution is required.

### Why Scorecard's Code-Review check will not go green here

Scorecard's `Code-Review` check scores a changeset as reviewed only when it
carries an **approving review from someone other than its author**. Cortex has
one maintainer, and GitHub structurally forbids approving your own pull request.
The check is therefore **unattainable by construction**, not unimplemented — no
configuration of this repository can satisfy it while it has a single
maintainer.

What is implemented instead is every part of the control that does not require a
second human: the pull-request requirement above (so no change reaches `main`
unreviewed by *machine* gates), the required-checks list, and the automated
analysis (CodeQL, Scorecard, Dependabot). The required approving-review count is
deliberately set to **0** rather than 1: at 1, a solo maintainer cannot merge at
all, so the setting would be traded for a repository that cannot ship — security
theatre that reduces real safety by pushing work outside the PR flow.

**The residual risk is real and is not claimed away:** a logic error that all
eleven automated gates accept will reach `main` without a second pair of human
eyes. Mitigation is the gate breadth above plus post-merge scanning; the honest
statement is that human code review is *absent*, not *satisfied*. This is why
the corresponding Scorecard alert is dismissed as "won't fix" rather than left
open — an alert that can never be actioned is noise that hides actionable ones.
It becomes actionable the moment a second maintainer joins, at which point the
approving-review count should be raised to 1 and this paragraph deleted.

**What this does NOT claim.** Provenance proves *who built the artifact and
from which commit*, not that the source is free of defects; and it is worth
nothing to a user who does not run the verification commands above. The
supported marketplace install path consumes the git tree directly
(ADR-0050), so its integrity is the tagged commit plus its attestation, not
a downloaded checksum. The container image built in CI is a bare-container
*smoke test* (`ci.yml`, `docker-smoke`) — it is never pushed to a registry,
so there is no published image to attest.

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
