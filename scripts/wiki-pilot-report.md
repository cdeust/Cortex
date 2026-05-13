# ADR-2244 Phase 2 — Pilot migration report

Wiki root: `/Users/cdeust/.claude/methodology/wiki`

## Summary

- **Sample size:** 100
- **Admitted by new classifier:** 88 (88.0%)
- **Rejected (admission gate):** 12 (12.0%)
- **Kind kept (legacy → modern direct map):** 77 (87.5% of admitted)
- **Kind changed:** 11 (12.5% of admitted)

## Distribution — legacy kinds in the sample

| Legacy kind | Pages |
|---|---:|
| `notes` | 23 |
| `reference` | 10 |
| `specs` | 9 |
| `adr` | 8 |
| `explanation` | 8 |
| `rfc` | 8 |
| `guides` | 8 |
| `conventions` | 8 |
| `lessons` | 8 |
| `adrs` | 8 |
| `README.md` | 1 |
| `architecture` | 1 |

## Distribution — proposed modern kinds

| Proposed kind | Pages |
|---|---:|
| `explanation` | 54 |
| `adr` | 16 |
| `<rejected>` | 12 |
| `reference` | 10 |
| `rfc` | 8 |

## Transition matrix (legacy → proposed)

| From | To | Count |
|---|---|---:|
| `notes` | `explanation` | 23 |
| `reference` | `reference` | 10 |
| `adr` | `adr` | 8 |
| `explanation` | `explanation` | 8 |
| `specs` | `<rejected>` | 8 |
| `rfc` | `rfc` | 8 |
| `guides` | `explanation` | 8 |
| `conventions` | `explanation` | 8 |
| `adrs` | `adr` | 8 |
| `lessons` | `explanation` | 4 |
| `lessons` | `<rejected>` | 4 |
| `README.md` | `explanation` | 1 |
| `specs` | `explanation` | 1 |
| `architecture` | `explanation` | 1 |

## Proposed facet distributions (admitted pages only)

### Lifecycle

| Value | Pages |
|---|---:|
| `seedling` | 72 |
| `proposed` | 16 |

### Audience (multi-valued — counted per occurrence)

| Value | Pages |
|---|---:|
| `developer` | 86 |
| `ops` | 15 |
| `security` | 10 |

### Provenance

| Value | Pages |
|---|---:|
| `auto-generated` | 46 |
| `human` | 42 |

## Rejection reasons

| Reason | Pages |
|---|---:|
| admission gate rejected (audit-tag, noise, or low score) | 12 |

## Per-page proposals

| Path | Legacy → Proposed | Lifecycle | Audience | Provenance | Status |
|---|---|---|---|---|---|
| `README.md` | `README.md` → `explanation` | `seedling` | `developer` | `human` | 🔁 changed |
| `adr/_general/2236-decision-003-felder-silverman-model.md.md` | `adr` → `adr` | `proposed` | `developer` | `human` | ✅ kept |
| `adr/agentic-ai/86789-decision-0004-validation-tool-optional-triple.md.md` | `adr` → `adr` | `proposed` | `developer` | `human` | ✅ kept |
| `adr/agentic-ai/96925-decision-0005-prd-spec-subtree-approach.md.md` | `adr` → `adr` | `proposed` | `developer` | `human` | ✅ kept |
| `adr/_general/2238-decision-005-agglomerative-over-kmeans-clustering.md.md` | `adr` → `adr` | `proposed` | `ops` | `human` | ✅ kept |
| `adr/_general/2234-decision-001-zero-dependencies.md.md` | `adr` → `adr` | `proposed` | `developer`, `ops` | `human` | ✅ kept |
| `adr/agentic-ai/96928-decision-0008-claude-plugin-path-placement.md.md` | `adr` → `adr` | `proposed` | `developer` | `human` | ✅ kept |
| `adr/agentic-ai/86792-decision-0007-better-sqlite3-native-build.md.md` | `adr` → `adr` | `proposed` | `developer`, `ops` | `human` | ✅ kept |
| `adr/agentic-ai/86787-decision-0002-analyze-codebase-serial-vs-parallel.md.md` | `adr` → `adr` | `proposed` | `developer` | `human` | ✅ kept |
| `explanation/codebase-alteration-bench/23744-file-storage-repository.py.md` | `explanation` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23738-file-auth-crypto.py.md` | `explanation` → `explanation` | `seedling` | `developer`, `security` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23739-file-auth-middleware.py.md` | `explanation` → `explanation` | `seedling` | `developer`, `security` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23768-file-api-health.py.md` | `explanation` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23779-file-api-routes.py.md` | `explanation` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23753-file-models-user.py.md` | `explanation` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23771-file-auth-middleware.py.md` | `explanation` → `explanation` | `seedling` | `developer`, `security` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23778-file-api-health.py.md` | `explanation` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `specs/_general/1173-reviewed-by-alexander-patterns-liskov-substitutability-hamilton.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/_general/2133-tool-bash.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/_general/2107-tool-bash.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/2026/2026-04-17-multiple-use-cases-and-a-pagingsource-in.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/_general/2087-tool-bash.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/_general/2207-tool-bash.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/2026/2026-04-17-jdk-21-temurin.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/_general/1820-spec-module-catalog-dcp-wealth-android.md` | `specs` → `explanation` | `seedling` | `developer` | `human` | 🔁 changed |
| `architecture/2026/2026-04-21-overview.md` | `architecture` → `explanation` | `seedling` | `developer`, `ops` | `human` | 🔁 changed |
| `rfc/repo-a/24695-project-structure-repo-a.md` | `rfc` → `rfc` | `seedling` | `developer` | `human` | ✅ kept |
| `rfc/repo-b/24071-project-structure-repo-b.md` | `rfc` → `rfc` | `seedling` | `developer` | `human` | ✅ kept |
| `rfc/repo-b/24655-project-structure-repo-b.md` | `rfc` → `rfc` | `seedling` | `developer` | `human` | ✅ kept |
| `rfc/repo-a/24068-project-structure-repo-a.md` | `rfc` → `rfc` | `seedling` | `developer` | `human` | ✅ kept |
| `rfc/repo-b/24698-project-structure-repo-b.md` | `rfc` → `rfc` | `seedling` | `developer` | `human` | ✅ kept |
| `rfc/repo-a/24664-project-structure-repo-a.md` | `rfc` → `rfc` | `seedling` | `developer` | `human` | ✅ kept |
| `rfc/repo-b/24077-project-structure-repo-b.md` | `rfc` → `rfc` | `seedling` | `developer` | `human` | ✅ kept |
| `rfc/repo-a/24658-project-structure-repo-a.md` | `rfc` → `rfc` | `seedling` | `developer` | `human` | ✅ kept |
| `notes/codebase-alteration-bench/12160-file-storage-user_repo.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/codebase-alteration-bench/9312-file-storage-user_repo.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/101422-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113856-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/109874-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/97741-file-packages-mcp-servers-reasoning-src-backend.ts.md` | `notes` → `explanation` | `seedling` | `developer`, `ops` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/98169-file-packages-memory-src-shared-hash.ts.md` | `notes` → `explanation` | `seedling` | `developer`, `security` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113272-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `guides/2026/2026-04-21-patterns.md` | `guides` → `explanation` | `seedling` | `developer` | `human` | 🔁 changed |
| `guides/2026/2026-04-21-user-flow.md` | `guides` → `explanation` | `seedling` | `security` | `human` | 🔁 changed |
| `guides/2026/2026-04-21-journeys.md` | `guides` → `explanation` | `seedling` | `developer`, `ops`, `security` | `human` | 🔁 changed |
| `guides/2026/2026-04-21-glossary.md` | `guides` → `explanation` | `seedling` | `developer`, `ops` | `human` | 🔁 changed |
| `guides/2026/2026-04-21-security.md` | `guides` → `explanation` | `seedling` | `developer`, `ops`, `security` | `human` | 🔁 changed |
| `guides/2026/2026-04-21-testing.md` | `guides` → `explanation` | `seedling` | `developer`, `security` | `human` | 🔁 changed |
| `guides/2026/2026-04-21-00-day-one.md` | `guides` → `explanation` | `seedling` | `developer`, `ops` | `human` | 🔁 changed |
| `guides/2026/2026-04-21-design-system.md` | `guides` → `explanation` | `seedling` | `developer` | `human` | 🔁 changed |
| `conventions/agentic-ai/86774-convention-p-align-center.md` | `conventions` → `explanation` | `seedling` | `developer`, `ops` | `human` | ✅ kept |
| `conventions/ai-architect-mcp/99075-convention-file-mcp-ai_architect_mcp-_adapters-git_adapter.py.md` | `conventions` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `conventions/agentic-ai/98438-convention-file-....md` | `conventions` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `conventions/ai-architect-mcp/99125-convention-file-mcp-ai_architect_mcp-_interview-scorers-outline_flow.py.md` | `conventions` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `conventions/agentic-ai/96936-convention-ci-cd-.github-workflows-ci.yml.md` | `conventions` → `explanation` | `seedling` | `developer`, `ops` | `human` | ✅ kept |
| `conventions/agentic-ai/96915-convention-phase_3_plan.md.md` | `conventions` → `explanation` | `seedling` | `developer`, `ops` | `human` | ✅ kept |
| `conventions/agentic-ai/96914-convention-patterns.md.md` | `conventions` → `explanation` | `seedling` | `developer` | `human` | ✅ kept |
| `conventions/ai-architect-mcp/99082-convention-file-mcp-ai_architect_mcp-_adapters-github_adapter.py.md` | `conventions` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `lessons/cortex/97502-lesson-file-tests_py-hooks-test_auto_recall.py.md` | `lessons` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `lessons/2026/2026-04-17-1-49-0.md` | `lessons` → `explanation` | `seedling` | `developer` | `human` | ✅ kept |
| `lessons/2026/2026-04-17-tool-bash.md` | `lessons` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `lessons/2026/2026-04-21-route-simulation-findings.md` | `lessons` → `explanation` | `seedling` | `developer` | `human` | ✅ kept |
| `lessons/agentic-ai/96917-lesson-phase_plan.md.md` | `lessons` → `explanation` | `seedling` | `developer`, `ops` | `human` | ✅ kept |
| `lessons/2026/2026-04-17-found-a-crash-when-coming-from-publication-push-notification.md` | `lessons` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `lessons/_general/1855-known-issues-and-technical-debt-dcp-wealth-android.md` | `lessons` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `lessons/2026/2026-04-17-c1-plaintext-backbase-artifactory-credentials-in-git.md` | `lessons` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `adrs/2026/2026-04-08-author-the-wiki-as-a-first-class-layer.md` | `adrs` → `adr` | `proposed` | `developer` | `human` | ✅ kept |
| `adrs/2026/2026-04-15-rotate-backbase-artifactory-credentials-committed-in-setting.md` | `adrs` → `adr` | `proposed` | `developer`, `ops` | `human` | ✅ kept |
| `adrs/2026/2026-04-15-network-security-config-allows-cleartext-and-lacks-certifica.md` | `adrs` → `adr` | `proposed` | `developer` | `human` | ✅ kept |
| `adrs/2026/2026-04-15-sgn-credentials-shipped-in-apk-via-ci-sed-injection.md` | `adrs` → `adr` | `proposed` | `developer`, `security` | `human` | ✅ kept |
| `adrs/2026/2026-04-15-maskingaction-only-masks-checkable-views-textview-pii-leaks.md` | `adrs` → `adr` | `proposed` | `developer` | `human` | ✅ kept |
| `adrs/2026/2026-04-08-manual-jacoco-agent-configuration-instead-of-the-jacoco-grad.md` | `adrs` → `adr` | `proposed` | `developer` | `human` | ✅ kept |
| `adrs/2026/2026-04-21-portfolio-details-declares-hilt-plugin-kapt-but-uses-ko.md` | `adrs` → `adr` | `proposed` | `developer` | `human` | ✅ kept |
| `adrs/2026/2026-04-15-myapplicationdependencies-is-a-1180-line-god-composition-roo.md` | `adrs` → `adr` | `proposed` | `developer`, `security` | `human` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-src-clustering-rs-cluster-graph.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-src-graph-store-rs-tests-test-create-and-query.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-tests-stage9-integration-rs-test-semantic-diff-missing-pa.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-tests-stage3d-integration-rs-test-search-partial-name.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-reasoning-memory-pii-scanner-py-main.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-src-graph-store-rs-tests-test-cypher-str-escape-rules.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-src-prd-validator-rs-tests-test-regex-extract-backtick.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-src-search-rrf-rs-tests-test-rrf-two-lists-fusion.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-mcp-servers-reasoning-src-index-ts-main.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112457-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/111282-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/104250-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112572-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/104329-file-library-.build-checkouts-nimble-sources-nimble-dsl-require.swift.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/104454-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `specs/_general/2096-tool-bash.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `notes/ai-architect-mcp/98901-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-src-lsp-client-rs-tests-test-parse-definition-array.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/101325-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113609-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113989-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/102607-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/codebase-alteration-bench/7578-file-storage-user_repo.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/103842-file-....md` | `notes` → `explanation` | `seedling` | `developer`, `ops` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113348-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112784-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
