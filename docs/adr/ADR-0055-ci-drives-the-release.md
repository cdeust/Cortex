# ADR-0055: CI drives the release — the tag is an output of the green tree

**Status:** Accepted
**Date:** 2026-08-08
**Decision-makers:** cdeust
**Related:** issue #392 (this change); issue #336 / PR #387 (the partial fix
this completes); release run
[30741657854](https://github.com/cdeust/Cortex/actions/runs/30741657854)
(v4.17.0, the incident); `.github/workflows/ci.yml::release-gate`;
`.github/workflows/release.yml`; `scripts/check_version_surfaces.py`;
ADR-0050 (marketplace is the primary install path, PyPI the best-effort
secondary).

## Context

`release.yml` did two jobs: it **tested**, then it **published**. Those two
roles have different trigger requirements, and the mismatch is what broke
v4.17.0.

`ci.yml` triggers on `push: branches: [main]` + `pull_request`.
`release.yml` triggers on `push: tags: ["v*"]`. **A tag push never reaches
`ci.yml`.** So `release.yml` carried its own copy of the pytest job, and
every network-hardening pass CI absorbed from 2026-07-27 onward applied to
one copy only. Nothing reported the drift, because drift between two files
with disjoint triggers is invisible until a release fails.

Measured cost: tag `v4.17.0` pointed at a tree that had just passed 20 green
checks on PR #334. Its release run hung anyway — FlashRank fetches its ONNX
model via `requests.get(stream=True)` with no timeout, so `HF_HUB_OFFLINE`
never reaches it and `reranker.py`'s `except Exception` cannot catch a
*hang*; the job blocked in `sock.connect` until pytest-timeout killed the
suite, and all five downstream publish jobs died on `needs: test`. v4.17.0
published nothing — no GitHub release, no PyPI upload, no `.mcpb` bundle.
#335 realigned the two copies by hand and shipped the result as v4.17.1.

Issue #336 / PR #387 extracted the shared pytest steps into a composite
action, so the two copies can no longer *diverge*. That fixed duplication.
It did not fix the dual role: `release.yml` still tested, its input
combination (`requirements/release.txt`, `include-tree-sitter: false`) was
still exercised by no branch CI, and a human could still push a tag at any
tree they liked.

## Decision

**Invert the relationship.** `ci.yml` decides; `release.yml` propagates.

A new `release-gate` job in `ci.yml` runs after `ci-green` on a push to
`main`. It detects a version bump (the tree's `[project].version` has no
corresponding tag), re-checks every version surface, and creates an
annotated tag at **the exact SHA that just went green**. `release.yml` keeps
its `push: tags` trigger and loses its `test` job entirely.

The tag stops being a hand-chosen *input* and becomes an *output* of a
validated tree. The v4.17.0 failure mode — a tag on a tree CI never
inspected — is no longer expressible: the only thing that creates a tag is
the job that runs after the gate.

## Rejected alternatives

**1. `ci.yml` calls `release.yml` via `workflow_call`.** This is what issue
#336 originally proposed and it reads as the obvious shape. It is
unavailable, for two independent reasons:

- **PyPI Trusted Publishing does not support reusable workflows**
  ([pypi/warehouse#11096](https://github.com/pypi/warehouse/issues/11096),
  [pypa/gh-action-pypi-publish#166](https://github.com/pypa/gh-action-pypi-publish/issues/166),
  both open as of 2026-08). This repo's publisher entry is keyed on
  `(cdeust/Cortex, release.yml, environment=pypi)`. Invoked via
  `workflow_call`, the OIDC claim carries the *caller's* workflow and the
  match fails. The failure would be **silent**: `publish-pypi` carries
  `continue-on-error: true`, so an identity mismatch reports yellow.
- **A job delegating via `uses:` renames its status check** to
  `<caller job> / <called job>`. PR #387 proved this in this very
  repository: its first pass converted the test job to `workflow_call`, all
  four matrix legs went green as `Test (Python X.Y) / Test (Python X.Y)`,
  and the PR sat BLOCKED because the four bare contexts required by `main`
  were reported by nobody. (This objection does not apply to a *new* job
  such as `release-gate`, which renames nothing — but the PyPI one is fatal
  on its own.)

**2. Keep tagging manual and simply delete `release.yml`'s test job.** This
is the status quo minus its only safety net. Nothing would then connect the
tagged tree to a green CI run at all.

**3. Trigger `release.yml` from `ci.yml` via `repository_dispatch`.** Works
around the `GITHUB_TOKEN` restriction below without a new credential, but
severs the tag from the release: `release.yml`'s `mcpb-bundle` job checks
`manifest.json.version` against `GITHUB_REF_NAME`, `github-release` derives
its notes from the tag range, and three attach steps use
`${{ github.ref_name }}` as the release name. A dispatch-triggered run has
no tag ref, so all of that would need reworking to carry the version as
payload — a larger change with no compensating benefit.

## Consequences

**A non-`GITHUB_TOKEN` credential is now required.** Per GitHub's docs,
"events triggered by the `GITHUB_TOKEN`, with the exception of
`workflow_dispatch` and `repository_dispatch`, will not create a new
workflow run." A tag pushed with the default token would therefore never
start `release.yml`. `release-gate` pushes over SSH with
`secrets.RELEASE_TAG_SSH_KEY` and **skips cleanly while that secret is
absent** — the same guarded-optional shape as `sync-ccplugins-fork.yml`'s
`CCPLUGINS_PAT`.

The credential is a **repository deploy key** — ed25519, `read_only=false`,
`verified: true`, created 2026-08-08 (`gh api repos/cdeust/Cortex/keys`) —
and not a fine-grained PAT or a GitHub App installation token. The deciding
constraint is operational, not aesthetic: neither a PAT nor a GitHub App can
be minted through the API, both require an interactive browser session,
while a deploy key is one `gh api` call. It is also the tightest of the
three by scope — one repository, no account access, no expiry date to
silently break releases later.

**What is not established.** That a deploy-key push *starts* `release.yml`
is a hypothesis, not a verified fact. GitHub documents the anti-recursion
rule for `GITHUB_TOKEN` only and says nothing about deploy keys; the claim
that they are exempt appears only in blog-level sources, and this repo holds
contradictory evidence on workflow chaining. The first real release is the
test. Failure mode if the hypothesis is wrong: the tag lands and no release
appears — visible immediately, recoverable by deleting the tag and pushing
it by hand. The complementary "no version bump → skip at the tag check" path
is likewise untested. Do not describe either as verified until a release has
exercised it.

The job declares `contents: read`, not `write`. The push authenticates with
the deploy key, so `write` on `GITHUB_TOKEN` would be an unused permission
(issue #178) — and worse, it would let a future edit that drops `ssh-key:`
from the checkout push the tag with `GITHUB_TOKEN` and *succeed*, producing
a tag that silently never starts `release.yml`. Read-only makes that mistake
fail loudly.

**`requirements/release.txt` needed a new home for its coverage.**
`release.yml`'s test job was the only thing that ever installed it. `ci.yml`
gained a `release-deps` job that installs it and smoke-imports the server on
every push and PR; without it, a broken release dependency set would surface
only at install time for a PyPI user.

**The version-surfaces gate became load-bearing.**
`scripts/check_version_surfaces.py` (issue #392, phase 1) is no longer only
a documentation check: a partial bump now blocks the tag. It runs twice — in
`lint` on every push and PR, and again inside `release-gate` immediately
before tagging. The second run is not redundant: `main` can be reached by a
direct push or an admin-merge override, and silently tagging a mismatched
tree is the failure class this ADR exists to prevent.

**`release-gate` sits outside the `ci-green` aggregate, by construction.**
It runs only after a PR has merged, so there is nothing left for it to gate;
listing it in `ci-green.needs` would make the branch-protection context
depend on a job that never runs on a PR, blocking every PR permanently.
`scripts/check_ci_gate_complete.py` — which otherwise requires every job to
be in that list — gained a `# ci-gate-exempt: <reason>` marker for this
case, refused unless the job also carries a job-level `if:`.

**`release.yml`'s `workflow_dispatch` still exists** and still serves its
original purpose (issue #246): exercising the pinned
checkout/cache/upload-artifact/download-artifact round trip on a real run
without shipping a release. Every release-producing step remains gated on
the tag-ref form.

**Cutting a release is now: bump, PR, merge.** No hand-pushed tag. See
CLAUDE.md § *Releasing*.
