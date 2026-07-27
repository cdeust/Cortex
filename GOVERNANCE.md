# Governance

Cortex is a single-maintainer open-source project. This document states who
decides what, how decisions are recorded, and what happens to the project if
the maintainer stops. It is deliberately short and literal: an aspirational
governance model nobody follows is worse than an accurate small one.

## Decision model

**Benevolent-dictator model with a written record.** The maintainer
([@cdeust](https://github.com/cdeust)) has final say on what ships. Anyone may
propose a change; the maintainer decides, and the reasoning is written down
where the decision lives:

| Decision | Where it is recorded |
|---|---|
| Architecture and cross-cutting design | an ADR under [`docs/adr/`](docs/adr/) |
| Whether a change lands | the pull request review |
| Whether a mechanism is scientifically grounded | the PR, against the five-element checklist in [CONTRIBUTING.md](CONTRIBUTING.md#adding-a-biological-mechanism) |
| What the project will and will not do next | [`docs/ROADMAP.md`](docs/ROADMAP.md) |
| Security handling | [SECURITY.md](SECURITY.md) |

Disputes are resolved on the merits, in public, on the issue or PR. The
standard the maintainer holds themselves to is the same one contributors are
held to: a claim needs a source, a number needs a measurement, and "it works"
is not evidence. Where a disagreement cannot be resolved, the MIT license
makes forking a legitimate outcome, not a failure.

## Roles and responsibilities

**Maintainer** — currently one person, [@cdeust](https://github.com/cdeust).
Responsibilities: review and merge pull requests; triage and answer issues;
cut releases and move the marketplace pins; respond to security reports within
the SLA in [SECURITY.md](SECURITY.md); keep the roadmap and the assurance case
current; decide scope.

**Contributor** — anyone who opens an issue or a pull request. Responsibilities:
follow [CONTRIBUTING.md](CONTRIBUTING.md) — tests with behaviour changes, a
source for every constant, no bypassed gates; keep the documentation the change
invalidates correct in the same PR.

**Security reporter** — anyone who reports a vulnerability privately through
the channel in [SECURITY.md](SECURITY.md). Responsibilities: report privately
first, allow the coordinated-disclosure window. In return the project owes a
first response within the stated SLA and public credit unless anonymity is
requested.

There is no separate committer, release-manager, or steering role today, and
this document will say so until that changes. The bus factor is therefore **1**
— stated plainly rather than papered over.

## Continuity of access

What the project would need in order to continue without the current
maintainer, and where it stands today:

**No release depends on a secret held by one person.** Publishing to PyPI uses
[Trusted Publishing](https://docs.pypi.org/trusted-publishers/) (OIDC — there
is no long-lived API token in the repository or in any personal keychain), and
artifact signing is Sigstore-keyless build provenance minted by the workflow
itself ([`.github/workflows/release.yml`](.github/workflows/release.yml)).
Anyone with write access to the repository can therefore cut a fully signed,
attested release without recovering a private key from anybody.

**Everything needed to rebuild the project is public.** Source, full git
history, tags, issue and PR history, CI and release workflows, the CycloneDX
SBOM attached to each release, and the benchmark reproduction harness are all
in this repository under the MIT license. There is no private build server, no
undocumented deployment step, and no hidden dependency on the maintainer's
machine.

**What is single-owner today:** administration of this GitHub repository, and
ownership of the `hypermnesia-mcp` project on PyPI. If the maintainer becomes
unavailable, those two cannot be transferred by the community on its own.

**The continuity path, concretely:** the MIT license permits anyone to fork,
publish under a new package name, and continue — with the complete history,
the same CI, and the same release pipeline, which needs only a repository and
its own Trusted Publishing entry to work. A fork can be issuing releases within
days, not months, because nothing in the pipeline is bespoke or secret.
Consumers pin through
[`.claude-plugin/marketplace.json`](.claude-plugin/marketplace.json), so a fork
publishing its own marketplace entry is a supported migration, not a hack.

Adding a second maintainer with repository admin — which is what would raise
the bus factor above 1 and remove the paragraph above — is on the roadmap
([`docs/ROADMAP.md`](docs/ROADMAP.md)).

## Contribution licensing (DCO / CLA)

The project has **no DCO sign-off requirement and no CLA today**. All
non-trivial code to date is the maintainer's own, licensed under MIT
([LICENSE](LICENSE)); contributions are accepted under the same license, as
stated in [CONTRIBUTING.md](CONTRIBUTING.md#license). If outside contributors
begin submitting non-trivial changes, a
[Developer Certificate of Origin](https://developercertificate.org/) sign-off
(`git commit -s`) is the mechanism this project will adopt — a CLA is
deliberately not planned, since assignment agreements deter contributors
without benefiting a project that has no corporate owner.

## Changing this document

This file changes by pull request like any other. A change to the decision
model or to the roles above is an ADR-worthy decision and gets one.
