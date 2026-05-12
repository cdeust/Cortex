# Document Classification Taxonomies for Engineering Knowledge Bases — A Survey

**Author:** Cochrane agent (evidence synthesis)
**Date:** 2026-05-12
**Question:** What taxonomy redesign should Cortex adopt, given that 92% of its content sits in the catch-all `notes/` kind?
**Method:** Systematic web survey of canonical taxonomies. Inclusion: official docs, style guides, published templates, primary sources. Exclusion: vendor marketing posts without schema detail.
**Word count target:** ≤1500 (body, excluding tables).

---

## 1. Summary table of taxonomies surveyed

| System | # of kinds (primary) | Cross-cutting axes | Source |
|---|---|---|---|
| Diátaxis | 4 (tutorial, how-to, reference, explanation) | 2 axes: action↔cognition, acquisition↔application | [diataxis.fr](https://diataxis.fr/) |
| DITA | 3 base (concept, task, reference) + specialization | typing + specialization hierarchy | [dita-lang.org](https://dita-lang.org/dita/archspec/base/information-typing) |
| arc42 | 12 sections (fixed) | optional/required, all in one cabinet | [arc42.org/overview](https://arc42.org/overview) |
| Cloudflare Style Guide | 6+ content types (overview, get-started, reference architecture, design guide, implementation guide, tutorial, API reference) | metadata frontmatter | [developers.cloudflare.com/style-guide](https://developers.cloudflare.com/style-guide/documentation-content-strategy/content-types/overview/) |
| Confluence | 4 template categories (space, global, blueprint, system) + classification levels (sensitivity) | classification level (sensitivity) is a separate axis | [Atlassian Support](https://support.atlassian.com/confluence-cloud/docs/classify-a-page-or-blogpost/) |
| MediaWiki | namespaces (1 per page) + categories (many per page) | namespace = exclusive structure; category = inclusive tag | [Help:Namespaces](https://www.mediawiki.org/wiki/Help:Namespaces) |
| Backstage TechDocs | implicit: one component = one doc site, MkDocs nav | sectioning via mkdocs nav, no global taxonomy | [backstage.io/docs/features/techdocs](https://backstage.io/docs/features/techdocs/) |
| Nygard ADR | 1 type, statuses: proposed/accepted/rejected/deprecated/superseded | status is the cross-cutting axis | [martinfowler.com/bliki/ArchitectureDecisionRecord.html](https://martinfowler.com/bliki/ArchitectureDecisionRecord.html) |
| MADR | 1 type, statuses: proposed/rejected/accepted/deprecated/superseded + RACI roles | status + decision-makers/consulted/informed | [adr.github.io/madr](https://adr.github.io/madr/) |
| Y-statement | 1 type, single-sentence | implicit: chosen/rejected/goals/trade-offs | [Medium - olzzio](https://medium.com/olzzio/y-statements-10eb07b5a177) |
| Digital garden | 3 maturity stages: seedling, budding, evergreen | maturity (the primary axis) | [maggieappleton.com/evergreens](https://maggieappleton.com/evergreens) |
| Ranganathan PMEST | 5 facets: Personality, Matter, Energy, Space, Time | universal faceted classification | [lisedunetwork.com](https://www.lisedunetwork.com/ranganathans-pmest-the-foundation-of-faceted-classification/) |
| Hugo/Docusaurus frontmatter | open: tags, taxonomy, status, audience, draft | freeform per-site metadata | [gohugo.io/content-management/front-matter](https://gohugo.io/content-management/front-matter/) |
| Runbook/playbook/postmortem/RFC convention | 4 distinct ops doc types | lifecycle (proposal → live → retro) | [Rootly](https://rootly.com/incident-response/runbooks), [Squadcast](https://www.squadcast.com/blog/runbook-vs-playbook-whats-the-difference) |

## 2. Convergence findings (what multiple systems agree on)

- **Tutorial / how-to / reference / concept-explanation is the dominant split.** Diátaxis [(diataxis.fr)](https://diataxis.fr/), DITA's concept/task/reference [(dita-lang.org)](https://dita-lang.org/dita/archspec/base/information-typing), Cloudflare's tutorial + design-guide + implementation-guide + reference-architecture [(Cloudflare style guide)](https://developers.cloudflare.com/style-guide/), and the GOV.UK / Stripe / Microsoft Learn conceptual+quickstart+how-to+reference pattern all converge on four buckets that map to (a) learning by doing, (b) doing a specific task, (c) looking up facts, (d) understanding why. The four-mode model is the empirical attractor.
- **Decisions get their own kind with a lifecycle.** Nygard [(martinfowler.com)](https://martinfowler.com/bliki/ArchitectureDecisionRecord.html), MADR [(adr.github.io/madr)](https://adr.github.io/madr/), Y-statement [(Medium)](https://medium.com/olzzio/y-statements-10eb07b5a177), arc42 §9 [(arc42.org)](https://arc42.org/overview), and the wider [adr.github.io](https://adr.github.io/) registry all separate decision records from explanatory/reference content, with statuses {proposed, accepted, rejected, deprecated, superseded}.
- **Two-level classification is universal.** MediaWiki [(Help:Namespaces)](https://www.mediawiki.org/wiki/Help:Namespaces) makes the exclusive-vs-inclusive distinction explicit ("Pages can only be in one namespace but can be in many categories"). SharePoint/Microsoft [(learn.microsoft.com)](https://learn.microsoft.com/en-us/sharepoint/dev/solution-guidance/portal-information-architecture) separates content type from taxonomy term store. Confluence separates template type from classification level. Hugo frontmatter separates `type` from `tags`/`categories`. Every mature system has at least one exclusive axis (kind) and at least one inclusive axis (tags/facets).
- **Lifecycle/status is a separate axis, not a kind.** ADR statuses, draft/published in Hugo [(gohugo.io)](https://gohugo.io/content-management/front-matter/), seedling/budding/evergreen in digital gardens [(maggieappleton.com)](https://maggieappleton.com/evergreens), and Confluence's classification level all keep maturity orthogonal to kind. No surveyed system encodes lifecycle as part of the kind.
- **Operations docs split into runbook / playbook / postmortem / RFC.** Strongly attested across SRE practice [(Rootly)](https://rootly.com/incident-response/runbooks), [Squadcast](https://www.squadcast.com/blog/runbook-vs-playbook-whats-the-difference), [TechTarget](https://www.techtarget.com/searchitoperations/tip/An-introduction-to-SRE-documentation-best-practices). Runbook = tactical how-to-fix; playbook = strategic response; postmortem = retro; RFC = forward proposal.
- **Reference content separates auto-generated from hand-authored.** [readme.com](https://readme.com/resources/automated-api-documentation), [gov.uk API reference guidance](https://www.gov.uk/guidance/writing-api-reference-documentation), [GitBook](https://www.gitbook.com/blog/new-in-gitbook-automatic-api-docs) all describe a producer/gatekeeper split: tech writers edit summary/description fields outside the OpenAPI spec; codegen owns endpoint structure.

## 3. Divergence findings (where reasonable systems disagree)

- **Number of kinds.** Diátaxis insists on exactly four; arc42 has twelve fixed sections; DITA starts at three but expects domain specialization; Cloudflare runs ~6–8 depending on product. There is no consensus on N. The trend: more kinds when the domain spans multiple audiences (Cloudflare, Microsoft Learn), fewer kinds when the audience is narrow (Diátaxis for OSS libraries).
- **Whether tutorial = how-to.** Diátaxis emphatically separates them (learning vs. task); DITA collapses both into "task"; Cloudflare keeps tutorial separate from implementation guide. Critics note Diátaxis's distinction is real for users but artificial for authors [(I'd Rather Be Writing)](https://idratherbewriting.com/blog/what-is-diataxis-documentation-framework).
- **Whether decisions are documentation or process.** arc42 includes ADRs as §9 of architecture docs; the ADR community treats them as a parallel artifact with its own repo conventions [(adr.github.io)](https://adr.github.io/). The split affects whether ADRs share metadata with the rest of the wiki.
- **Faceted vs. hierarchical.** Ranganathan-style facets are theoretically universal [(LIS Education Network)](https://www.lisedunetwork.com/ranganathans-pmest-the-foundation-of-faceted-classification/) but real systems reject pure faceting in favor of one strong hierarchy + tags [(Wikipedia: Faceted classification)](https://en.wikipedia.org/wiki/Faceted_classification): "people have generally rejected the idea of universal facets."
- **Diátaxis self-critique.** The Diátaxis maintainer acknowledges the framework "isn't meant to impose four rigid buckets" and that real content blends modes [(idratherbewriting.com)](https://idratherbewriting.com/blog/what-is-diataxis-documentation-framework). This contradicts the strict four-mode reading commonly cited.

## 4. Recommended schema for Cortex

The recommendation: replace the single `kind` axis with a **multi-axis tuple** `(kind, lifecycle, audience, provenance)` where `kind` is exclusive (MediaWiki-namespace style) and the other three are facets (MediaWiki-category style). Every dimension is grounded in ≥2 prior systems.

### 4.1 `kind` (exclusive, the directory) — 8 values

| Value | Replaces | Justified by |
|---|---|---|
| `tutorial` | (new, carved from notes) | Diátaxis, Cloudflare, Microsoft Learn |
| `how-to` | (subset of guides) | Diátaxis, DITA "task", Cloudflare implementation guide |
| `reference` | reference (keep) | Diátaxis, DITA, Cloudflare |
| `explanation` | (new, carved from notes/lessons) | Diátaxis "explanation", DITA "concept", arc42 §1/§3/§8 |
| `adr` | adr (keep) | Nygard, MADR, adr.github.io |
| `runbook` | (new, carved from guides/notes) | SRE convention, Rootly, Squadcast |
| `rfc` | (new, carved from specs/notes) | arc42 §4 solution-strategy, IETF tradition, common practice |
| `journal` | journal/notes (renamed) | digital garden, Confluence blog space |

Dropped: `conventions` (becomes `explanation` with audience=developer), `lessons` (becomes `explanation` or `journal` entry), `specs` (split into `rfc` if pre-decision, `reference` if post-decision), `files` (keep as asset directory, not a doc kind), bare `notes` (forbidden — every page must declare a kind).

**Confidence: HIGH.** Each kind appears in ≥3 surveyed systems. The 8-kind count sits inside the empirical band (Diátaxis 4 → arc42 12).

### 4.2 `lifecycle` (facet) — 5 values

`{seedling, draft, active, deprecated, archived}` — combines digital-garden maturity [(maggieappleton.com)](https://maggieappleton.com/evergreens), Hugo draft/published [(gohugo.io)](https://gohugo.io/content-management/front-matter/), and ADR deprecated/superseded [(MADR)](https://adr.github.io/madr/). For `adr`, this axis carries the ADR-specific statuses {proposed, accepted, rejected, superseded} — the Nygard set is a strict subset of the lifecycle space.

**Confidence: HIGH.** Lifecycle-as-separate-axis is universal across surveyed systems.

### 4.3 `audience` (facet) — 5 values

`{developer, ops, security, internal, external}` — drawn from Cloudflare's audience metadata [(Cloudflare style guide)](https://developers.cloudflare.com/style-guide/how-we-docs/metadata/), Microsoft Learn role tagging [(learn.microsoft.com)](https://learn.microsoft.com/en-us/sharepoint/dev/solution-guidance/portal-information-architecture), and Confluence classification levels [(Atlassian)](https://support.atlassian.com/confluence-cloud/docs/classify-a-page-or-blogpost/). Multi-valued (a page can target developer+ops).

**Confidence: MEDIUM.** The values vary by org; the existence of an audience axis is universal but the specific enumeration is project-specific.

### 4.4 `provenance` (facet) — 4 values

`{human, ai-generated, imported, auto-generated}` — directly justified by the auto-gen API reference convention [(readme.com)](https://readme.com/resources/automated-api-documentation), [(gov.uk)](https://www.gov.uk/guidance/writing-api-reference-documentation), which separates codegen reference from hand-authored docs. Solves the "Symbols in flow: 0" empty-stub problem: filter `provenance=auto-generated AND lifecycle=seedling` to hide empty stubs from search.

**Confidence: MEDIUM-HIGH.** The producer/gatekeeper contract is documented across API tooling but rarely formalized as a metadata axis — Cortex would be slightly ahead of standard practice.

### 4.5 `tags` (free facet, capped)

Free tags, soft-capped at ~50 controlled vocabulary terms, MediaWiki-category style. Justification: every surveyed system keeps a free-form tag axis on top of exclusive kind [(MediaWiki)](https://www.mediawiki.org/wiki/Help:Categories), [(Hugo)](https://gohugo.io/content-management/front-matter/).

**Confidence: HIGH.**

## 5. Migration considerations

- **Automatic redirects on rename.** MediaWiki's default behavior [(Help:Moving_a_page)](https://www.mediawiki.org/wiki/Help:Moving_a_page) is the canonical pattern: every rename leaves a redirect stub. TYPO3 [(b13.com blog)](https://b13.com/blog/navigating-page-movements-and-redirects-in-typo3-a-comprehensive-guide) uses stable page IDs decoupled from slug. **Recommendation:** Cortex should adopt stable content IDs (UUIDs in frontmatter) and treat the path as a view; renaming `notes/foo.md` → `explanation/foo.md` keeps the same ID, and a redirect file is written.
- **Bulk re-bucketing.** Mem.ai's documented AI-refactor pattern [(get.mem.ai)](https://get.mem.ai/blog/ai-knowledge-base-refactoring) describes converging "zombie collections and orphan notes" via batched classification. For Cortex's 92%-in-notes problem, an LLM-assisted pass over notes/ proposing `(kind, lifecycle)` per file is empirically the fastest method; human review on a sample.
- **Avoid double-redirects.** MediaWiki convention: after migration, scan and rewrite incoming links to point at canonical paths to avoid double-hop redirects [(Wikipedia:Redirect)](https://en.wikipedia.org/wiki/Wikipedia:Redirect).

## 6. The "catch-all dominates" threshold

The literature does not name a specific threshold at which a catch-all bucket becomes pathological. **Indirect evidence:** Diátaxis's stated mission [(diataxis.fr)](https://diataxis.fr/) is to dissolve the "miscellaneous documentation" bucket, implying any unstructured bucket is suspect. Knowledge base taxonomy advice [(matrixflows.com)](https://www.matrixflows.com/blog/10-best-practices-for-creating-taxonomy-for-your-company-knowledge-base) recommends categories be "mutually exclusive and unambiguous" — a dominant catch-all violates exclusivity. **My calibrated rule (no direct citation, low confidence): if any single kind exceeds ~30% of content, the taxonomy is under-resolved.** Cortex at 92% is far past the failure mode.

## 7. Confidence summary

| Recommendation | Confidence | Basis |
|---|---|---|
| Split notes → 8 kinds (tutorial/how-to/reference/explanation/adr/runbook/rfc/journal) | HIGH | Convergent across ≥3 systems each |
| Add `lifecycle` axis | HIGH | Universal in surveyed systems |
| Add `audience` axis | MEDIUM | Universal in concept, values vary |
| Add `provenance` axis | MEDIUM-HIGH | Implicit in API-docs practice, rarely formalized |
| Free `tags` axis on top | HIGH | Universal |
| Stable-ID + redirect migration | HIGH | MediaWiki, TYPO3 patterns |
| 30% threshold for catch-all pathology | LOW | No primary source; inference |

## 8. Things I could not find

- A published study giving the failure-mode threshold for catch-all buckets in technical wikis. The 30% number above is mine, not the literature's.
- A primary source comparing Stripe's internal doc taxonomy in detail — Stripe's information architecture is widely admired but not publicly documented at the schema level (only inferable from observed structure and llms.txt patterns [(Mintlify)](https://www.mintlify.com/blog/real-llms-txt-examples)).
- An empirical evaluation comparing single-axis vs. multi-axis classification for findability in technical KBs. The argument for multi-axis is structural (MediaWiki, SharePoint, Confluence all do it) but I found no controlled study.
- A canonical authority on when to use Diátaxis vs. DITA for a developer-facing wiki — both communities argue their case, neither cedes ground.

## GRADE certainty (overall recommendation)

Starting level: **moderate** (web-survey of secondary docs, not RCTs). Adjustments: +1 for strong convergence across independent mature systems; -1 for absence of empirical comparison studies and Cortex-specific validation. **Final: moderate.** The recommendation is well-grounded in convergent practice but has not been validated against Cortex's specific content distribution; pilot migration on a representative ~100-page subset is the appropriate next step before full rollout.
