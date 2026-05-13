# ADR-2244 Phase 2 — Pilot migration report

Wiki root: `/Users/cdeust/.claude/methodology/wiki`

## Summary

- **Sample size:** 1000
- **Admitted by new classifier:** 942 (94.2%)
- **Rejected (admission gate):** 58 (5.8%)
- **Kind kept (legacy → modern direct map):** 911 (96.7% of admitted)
- **Kind changed:** 31 (3.3% of admitted)

## Distribution — legacy kinds in the sample

| Legacy kind | Pages |
|---|---:|
| `notes` | 617 |
| `reference` | 111 |
| `specs` | 68 |
| `conventions` | 54 |
| `explanation` | 52 |
| `adr` | 31 |
| `lessons` | 21 |
| `rfc` | 18 |
| `adrs` | 15 |
| `guides` | 11 |
| `README.md` | 1 |
| `architecture` | 1 |

## Distribution — proposed modern kinds

| Proposed kind | Pages |
|---|---:|
| `explanation` | 754 |
| `reference` | 111 |
| `<rejected>` | 58 |
| `adr` | 43 |
| `rfc` | 29 |
| `how-to` | 4 |
| `runbook` | 1 |

## Transition matrix (legacy → proposed)

| From | To | Count |
|---|---|---:|
| `notes` | `explanation` | 614 |
| `reference` | `reference` | 111 |
| `explanation` | `explanation` | 52 |
| `conventions` | `explanation` | 52 |
| `specs` | `<rejected>` | 46 |
| `adr` | `adr` | 29 |
| `rfc` | `rfc` | 18 |
| `adrs` | `adr` | 14 |
| `specs` | `explanation` | 11 |
| `specs` | `rfc` | 11 |
| `guides` | `explanation` | 11 |
| `lessons` | `<rejected>` | 10 |
| `lessons` | `explanation` | 10 |
| `adr` | `explanation` | 2 |
| `conventions` | `how-to` | 2 |
| `README.md` | `explanation` | 1 |
| `architecture` | `explanation` | 1 |
| `notes` | `<rejected>` | 1 |
| `lessons` | `how-to` | 1 |
| `adrs` | `<rejected>` | 1 |
| `notes` | `runbook` | 1 |
| `notes` | `how-to` | 1 |

## Proposed facet distributions (admitted pages only)

### Lifecycle

| Value | Pages |
|---|---:|
| `seedling` | 899 |
| `proposed` | 43 |

### Audience (multi-valued — counted per occurrence)

| Value | Pages |
|---|---:|
| `developer` | 935 |
| `ops` | 90 |
| `security` | 48 |

### Provenance

| Value | Pages |
|---|---:|
| `auto-generated` | 809 |
| `human` | 133 |

## Rejection reasons

| Reason | Pages |
|---|---:|
| admission gate rejected (audit-tag, noise, or low score) | 58 |

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
| `adr/_general/2242-decision-009-node-test-over-jest.md.md` | `adr` → `adr` | `proposed` | `developer`, `ops` | `human` | ✅ kept |
| `adr/_general/2239-decision-006-ema-for-incremental-updates.md.md` | `adr` → `adr` | `proposed` | `developer` | `human` | ✅ kept |
| `adr/_general/2237-decision-004-jaccard-over-cosine-similarity.md.md` | `adr` → `adr` | `proposed` | `developer` | `human` | ✅ kept |
| `adr/agentic-ai/86786-decision-0001-lsp-resolve-subprocess-chain.md.md` | `adr` → `adr` | `proposed` | `developer` | `human` | ✅ kept |
| `adr/agentic-ai/96922-decision-0002-analyze-codebase-serial-vs-parallel.md.md` | `adr` → `adr` | `proposed` | `developer` | `human` | ✅ kept |
| `adr/agentic-ai/86788-decision-0003-adapter-precondition-strength.md.md` | `adr` → `adr` | `proposed` | `developer` | `human` | ✅ kept |
| `adr/_general/2244-richer-wiki-classification.md` | `adr` → `adr` | `proposed` | `developer`, `ops` | `human` | ✅ kept |
| `adr/agentic-ai/86793-decision-0008-claude-plugin-path-placement.md.md` | `adr` → `adr` | `proposed` | `developer` | `human` | ✅ kept |
| `adr/agentic-ai/96927-decision-0007-better-sqlite3-native-build.md.md` | `adr` → `adr` | `proposed` | `developer`, `ops` | `human` | ✅ kept |
| `adr/_general/1830-decision-created-2026-04-15t09-29-10z.md` | `adr` → `explanation` | `seedling` | `developer` | `human` | 🔁 changed |
| `adr/agentic-ai/96926-decision-0006-prd-bundle-preserve-vs-regenerate.md.md` | `adr` → `adr` | `proposed` | `developer` | `human` | ✅ kept |
| `adr/_general/2240-decision-007-head-tail-jsonl-reading.md.md` | `adr` → `adr` | `proposed` | `developer` | `human` | ✅ kept |
| `adr/_general/2235-decision-002-clean-architecture-layers.md.md` | `adr` → `adr` | `proposed` | `developer`, `ops` | `human` | ✅ kept |
| `adr/agentic-ai/96924-decision-0004-validation-tool-optional-triple.md.md` | `adr` → `adr` | `proposed` | `developer` | `human` | ✅ kept |
| `adr/agentic-ai/96921-decision-0001-lsp-resolve-subprocess-chain.md.md` | `adr` → `adr` | `proposed` | `developer` | `human` | ✅ kept |
| `adr/agentic-ai/86790-decision-0005-prd-spec-subtree-approach.md.md` | `adr` → `adr` | `proposed` | `developer` | `human` | ✅ kept |
| `adr/_general/2241-decision-008-handler-as-composition-root.md.md` | `adr` → `adr` | `proposed` | `developer`, `ops` | `human` | ✅ kept |
| `adr/_general/2224-decision-p-align-center.md` | `adr` → `adr` | `proposed` | `developer`, `ops`, `security` | `human` | ✅ kept |
| `adr/_general/2243-decision-010-sparse-dictionary-learning.md.md` | `adr` → `adr` | `proposed` | `ops` | `human` | ✅ kept |
| `adr/_general/2232-decision-cortex-a-neuroscience-grounded-persistent-memory-system-for-code-assist.md` | `adr` → `adr` | `proposed` | `developer`, `ops` | `human` | ✅ kept |
| `adr/agentic-ai/96923-decision-0003-adapter-precondition-strength.md.md` | `adr` → `adr` | `proposed` | `developer` | `human` | ✅ kept |
| `adr/agentic-ai/86791-decision-0006-prd-bundle-preserve-vs-regenerate.md.md` | `adr` → `adr` | `proposed` | `developer` | `human` | ✅ kept |
| `adr/_general/1828-decision-created-2026-04-15t09-29-10z.md` | `adr` → `explanation` | `seedling` | `developer` | `human` | 🔁 changed |
| `explanation/codebase-alteration-bench/23782-file-auth-token_service.py.md` | `explanation` → `explanation` | `seedling` | `developer`, `security` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23774-file-models-session.py.md` | `explanation` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23742-file-models-session.py.md` | `explanation` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23753-file-models-user.py.md` | `explanation` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23736-file-api-health.py.md` | `explanation` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23785-file-models-user.py.md` | `explanation` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23777-file-storage-user_repo.py.md` | `explanation` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23739-file-auth-middleware.py.md` | `explanation` → `explanation` | `seedling` | `developer`, `security` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23738-file-auth-crypto.py.md` | `explanation` → `explanation` | `seedling` | `developer`, `security` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23771-file-auth-middleware.py.md` | `explanation` → `explanation` | `seedling` | `developer`, `security` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23752-file-models-session.py.md` | `explanation` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23750-file-auth-token_service.py.md` | `explanation` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23779-file-api-routes.py.md` | `explanation` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23778-file-api-health.py.md` | `explanation` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23784-file-models-session.py.md` | `explanation` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23781-file-auth-middleware.py.md` | `explanation` → `explanation` | `seedling` | `developer`, `security` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23745-file-storage-user_repo.py.md` | `explanation` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23765-file-models-user.py.md` | `explanation` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23761-file-auth-middleware.py.md` | `explanation` → `explanation` | `seedling` | `developer`, `security` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23751-file-config-settings.py.md` | `explanation` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23768-file-api-health.py.md` | `explanation` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23737-file-api-routes.py.md` | `explanation` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23775-file-models-user.py.md` | `explanation` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23755-file-storage-user_repo.py.md` | `explanation` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23762-file-auth-token_service.py.md` | `explanation` → `explanation` | `seedling` | `developer`, `security` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23766-file-storage-repository.py.md` | `explanation` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23776-file-storage-repository.py.md` | `explanation` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23773-file-config-settings.py.md` | `explanation` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23757-file-auth-token_service.py.md` | `explanation` → `explanation` | `seedling` | `developer`, `security` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23746-file-api-health.py.md` | `explanation` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23749-file-auth-middleware.py.md` | `explanation` → `explanation` | `seedling` | `developer`, `security` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23763-file-config-settings.py.md` | `explanation` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23770-file-auth-crypto.py.md` | `explanation` → `explanation` | `seedling` | `developer`, `security` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23743-file-models-user.py.md` | `explanation` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23767-file-storage-user_repo.py.md` | `explanation` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23783-file-config-settings.py.md` | `explanation` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23780-file-auth-crypto.py.md` | `explanation` → `explanation` | `seedling` | `developer`, `security` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23758-file-api-health.py.md` | `explanation` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23760-file-auth-crypto.py.md` | `explanation` → `explanation` | `seedling` | `developer`, `security` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23769-file-api-routes.py.md` | `explanation` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23786-file-storage-repository.py.md` | `explanation` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23741-file-config-settings.py.md` | `explanation` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23747-file-api-routes.py.md` | `explanation` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23748-file-auth-crypto.py.md` | `explanation` → `explanation` | `seedling` | `developer`, `security` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23740-file-auth-token_service.py.md` | `explanation` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23756-file-auth-middleware.py.md` | `explanation` → `explanation` | `seedling` | `developer`, `security` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23759-file-api-routes.py.md` | `explanation` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23787-file-storage-user_repo.py.md` | `explanation` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23772-file-auth-token_service.py.md` | `explanation` → `explanation` | `seedling` | `developer`, `security` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23764-file-models-session.py.md` | `explanation` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23744-file-storage-repository.py.md` | `explanation` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `explanation/codebase-alteration-bench/23754-file-storage-repository.py.md` | `explanation` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `specs/_general/2207-tool-bash.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/2026/2026-04-08-wiki-authoring-layer.md` | `specs` → `explanation` | `seedling` | `developer` | `human` | 🔁 changed |
| `specs/agentic-ai/86798-spec-entry-point-packages-memory-src-methodology-index.ts.md` | `specs` → `rfc` | `seedling` | `developer`, `ops` | `human` | ✅ kept |
| `specs/_general/2107-tool-bash.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/agentic-ai/96931-spec-entry-point-packages-core-src-index.ts.md` | `specs` → `rfc` | `seedling` | `developer` | `human` | ✅ kept |
| `specs/_general/2061-tool-bash.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/2026/2026-04-17-region-dependency-declarations.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/_general/1820-spec-module-catalog-dcp-wealth-android.md` | `specs` → `explanation` | `seedling` | `developer` | `human` | 🔁 changed |
| `specs/agentic-ai/96930-spec-entry-point-packages-parity-runner-src-index.ts.md` | `specs` → `rfc` | `seedling` | `developer`, `ops` | `human` | ✅ kept |
| `specs/_general/1959-tool-bash.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/_general/1173-reviewed-by-alexander-patterns-liskov-substitutability-hamilton.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/_general/2221-spec-project-structure-cortex.md` | `specs` → `explanation` | `seedling` | `developer` | `human` | 🔁 changed |
| `specs/agentic-ai/86795-spec-entry-point-packages-parity-runner-src-index.ts.md` | `specs` → `rfc` | `seedling` | `developer`, `ops` | `human` | ✅ kept |
| `specs/_general/1177-tool-bash.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/2026/2026-04-17-remember-that-we-re-not-making-custom-code-for-benchmark-we.md` | `specs` → `explanation` | `seedling` | `developer` | `human` | 🔁 changed |
| `specs/_general/2023-tool-bash.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/_general/2043-tool-bash.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/_general/2087-tool-bash.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/agentic-ai/86796-spec-entry-point-packages-core-src-index.ts.md` | `specs` → `rfc` | `seedling` | `developer` | `human` | ✅ kept |
| `specs/2026/2026-04-17-tool-bash.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/2026/2026-04-17-also-on-users-cdeust-documents-developments-ai-architect-prd.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/_general/2171-tool-bash.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/_general/1877-component-version-source.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/2026/2026-04-17-tool-version-source.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/2026/2026-04-17-multiple-use-cases-and-a-pagingsource-in.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/_general/2108-tool-bash.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/_general/1819-spec-architecture-overview-dcp-wealth-android.md` | `specs` → `explanation` | `seedling` | `developer` | `human` | 🔁 changed |
| `specs/2026/2026-04-17-the-agent-registry-have-been-updated-the-graph-should-be-upd.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/2026/2026-04-17-the-intent-reached-myactivity-onnewintent.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/2026/2026-04-17-the-default-sonarcloud-cognitive-complexity-rule-kotlin-s377.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/_general/1881-spec-architecture-overview-dcp-wealth-android.md` | `specs` → `explanation` | `seedling` | `developer` | `human` | 🔁 changed |
| `specs/_general/2245-spec-entry-point-mcp_server-__main__.py.md` | `specs` → `explanation` | `seedling` | `developer`, `ops` | `human` | 🔁 changed |
| `specs/_general/2195-tool-bash.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/_general/2119-tool-bash.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/2026/2026-04-17-tool-write.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/agentic-ai/86772-spec-project-structure-agentic-ai.md` | `specs` → `rfc` | `seedling` | `developer` | `human` | ✅ kept |
| `specs/_general/2096-tool-bash.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/_general/2026-tool-bash.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/agentic-ai/96907-spec-project-structure-agentic-ai.md` | `specs` → `rfc` | `seedling` | `developer` | `human` | ✅ kept |
| `specs/_general/2098-tool-bash.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/_general/2202-tool-bash.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/dcp-wealth-android/64431-spec-project-structure-dcp-wealth-android.md` | `specs` → `rfc` | `seedling` | `developer` | `human` | ✅ kept |
| `specs/2026/2026-04-17-didn-t-set-out-to-build-a-tool.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/_general/2181-tool-bash.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/_general/2064-tool-bash.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/_general/1847-spec-module-catalog-dcp-wealth-android.md` | `specs` → `explanation` | `seedling` | `developer` | `human` | 🔁 changed |
| `specs/dcp-wealth-android/1914-tool-bash.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/agentic-ai/96933-spec-entry-point-packages-memory-src-methodology-index.ts.md` | `specs` → `rfc` | `seedling` | `developer`, `ops` | `human` | ✅ kept |
| `specs/_general/2133-tool-bash.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/agentic-ai/96932-spec-entry-point-packages-memory-src-index.ts.md` | `specs` → `rfc` | `seedling` | `developer` | `human` | ✅ kept |
| `specs/_general/1159-tool-bash.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/dcp-wealth-android/1814-tool-bash.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/2026/2026-04-17-layer-choice-version-source.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/2026/2026-04-17-jdk-21-temurin.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/_general/2103-tool-bash.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/2026/2026-04-17-page.md` | `specs` → `explanation` | `seedling` | `developer` | `human` | 🔁 changed |
| `specs/_general/2136-tool-bash.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/_general/1881-layer-choice-version-source.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/_general/2009-tool-bash.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/_general/2265-tool-bash.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/agentic-ai/86797-spec-entry-point-packages-memory-src-index.ts.md` | `specs` → `rfc` | `seedling` | `developer` | `human` | ✅ kept |
| `specs/_general/1848-component-version-source.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/_general/2172-tool-bash.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/2026/2026-04-17-your-role.md` | `specs` → `explanation` | `seedling` | `developer` | `human` | 🔁 changed |
| `specs/_general/2244-spec-entry-point-ui-methodology-js-main.js.md` | `specs` → `explanation` | `seedling` | `developer` | `human` | 🔁 changed |
| `specs/_general/2144-tool-bash.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/_general/2196-tool-bash.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `specs/2026/2026-04-17-component-version-source.md` | `specs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `architecture/2026/2026-04-21-overview.md` | `architecture` → `explanation` | `seedling` | `developer`, `ops` | `human` | 🔁 changed |
| `rfc/repo-b/24704-project-structure-repo-b.md` | `rfc` → `rfc` | `seedling` | `developer` | `human` | ✅ kept |
| `rfc/repo-a/24664-project-structure-repo-a.md` | `rfc` → `rfc` | `seedling` | `developer` | `human` | ✅ kept |
| `rfc/repo-a/24695-project-structure-repo-a.md` | `rfc` → `rfc` | `seedling` | `developer` | `human` | ✅ kept |
| `rfc/repo-b/24077-project-structure-repo-b.md` | `rfc` → `rfc` | `seedling` | `developer` | `human` | ✅ kept |
| `rfc/repo-a/24068-project-structure-repo-a.md` | `rfc` → `rfc` | `seedling` | `developer` | `human` | ✅ kept |
| `rfc/repo-b/24655-project-structure-repo-b.md` | `rfc` → `rfc` | `seedling` | `developer` | `human` | ✅ kept |
| `rfc/repo-b/24071-project-structure-repo-b.md` | `rfc` → `rfc` | `seedling` | `developer` | `human` | ✅ kept |
| `rfc/repo-a/24707-project-structure-repo-a.md` | `rfc` → `rfc` | `seedling` | `developer` | `human` | ✅ kept |
| `rfc/auto-detect-me/24710-project-structure-auto-detect-me.md` | `rfc` → `rfc` | `seedling` | `developer` | `human` | ✅ kept |
| `rfc/repo-b/24698-project-structure-repo-b.md` | `rfc` → `rfc` | `seedling` | `developer` | `human` | ✅ kept |
| `rfc/auto-detect-me/24667-project-structure-auto-detect-me.md` | `rfc` → `rfc` | `seedling` | `developer` | `human` | ✅ kept |
| `rfc/repo-b/24661-project-structure-repo-b.md` | `rfc` → `rfc` | `seedling` | `developer` | `human` | ✅ kept |
| `rfc/repo-a/24080-project-structure-repo-a.md` | `rfc` → `rfc` | `seedling` | `developer` | `human` | ✅ kept |
| `rfc/repo-a/24701-project-structure-repo-a.md` | `rfc` → `rfc` | `seedling` | `developer` | `human` | ✅ kept |
| `rfc/auto-detect-me/24083-project-structure-auto-detect-me.md` | `rfc` → `rfc` | `seedling` | `developer` | `human` | ✅ kept |
| `rfc/repo-a/24652-project-structure-repo-a.md` | `rfc` → `rfc` | `seedling` | `developer` | `human` | ✅ kept |
| `rfc/repo-a/24074-project-structure-repo-a.md` | `rfc` → `rfc` | `seedling` | `developer` | `human` | ✅ kept |
| `rfc/repo-a/24658-project-structure-repo-a.md` | `rfc` → `rfc` | `seedling` | `developer` | `human` | ✅ kept |
| `notes/ai-prd/106247-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112745-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/97764-file-packages-memory-__tests__-consolidation-homeostatic-health.test.ts.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/108391-file-library-.build-checkouts-swift-crypto-sources-cryptoextras-key....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/101718-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/2026/2026-04-17-live-runtime-findings-discovered-2026-04-15-on-a-logged-in-i.md` | `notes` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `notes/agentic-ai/97903-file-packages-memory-__tests__-wiki-templates-schema.test.ts.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/108854-file-library-.build-checkouts-swift-nio-sources-nioposix-socket.swift.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112898-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/108015-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113506-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/108012-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/107511-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112061-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/108218-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/104664-file-library-.build-checkouts-quick-sources-quick-async-asyncexamplegroup.swift.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/cortex/97220-file-mcp_server-handlers-recompute_layout.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112581-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/106962-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112980-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/97874-file-packages-memory-__tests__-remember-remember-response.test.ts.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/cortex/97080-file-mcp_server-core-platt_calibration.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/108455-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/98380-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/104452-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/109872-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/codebase-alteration-bench/7582-file-auth-middleware.py.md` | `notes` → `explanation` | `seedling` | `developer`, `security` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/109674-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/103595-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/102350-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/100732-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/107247-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112480-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/codebase-alteration-bench/15385-file-storage-user_repo.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/114247-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113312-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-mcp/98944-file-ai-codebase-intelligence-src-ai_codebase_intelligence-core-graph-types.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/105619-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113462-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/107772-file-....md` | `notes` → `explanation` | `seedling` | `developer`, `ops` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/97846-file-packages-memory-__tests__-recall-knowledge-graph.test.ts.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113429-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/102704-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112930-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112073-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-mcp/98910-file-ai-codebase-intelligence-src-ai_codebase_intelligence-_wiki-prompts.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/104099-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/109033-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112846-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113160-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113300-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112096-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-feedback-loop/98797-file-scripts-setup_wizard.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/cortex/97052-file-mcp_server-core-graph_builder_edges.py.md` | `notes` → `explanation` | `seedling` | `developer`, `ops` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113007-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-mcp/99135-file-mcp-ai_architect_mcp-_models-finding.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/104463-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/114016-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/101585-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-mcp/98925-file-ai-codebase-intelligence-src-ai_codebase_intelligence-cli-wiki.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/codebase-alteration-bench/5020-file-auth-crypto.py.md` | `notes` → `explanation` | `seedling` | `developer`, `security` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112501-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/101515-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/_general/2222-package.json.md` | `notes` → `explanation` | `seedling` | `developer` | `human` | ✅ kept |
| `notes/ai-prd-generator/113176-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/101376-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/109655-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/104465-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112573-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/107999-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/102917-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/104643-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/103315-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112032-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/98450-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112927-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112773-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/codebase-alteration-bench/1552-file-auth-token_service.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/114153-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/101960-file-....md` | `notes` → `explanation` | `seedling` | `developer`, `ops` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112897-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/109679-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/104435-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `guides/2026/2026-04-21-glossary.md` | `guides` → `explanation` | `seedling` | `developer`, `ops` | `human` | 🔁 changed |
| `guides/2026/2026-04-21-build-and-ci.md` | `guides` → `explanation` | `seedling` | `developer` | `human` | 🔁 changed |
| `guides/2026/2026-04-21-patterns.md` | `guides` → `explanation` | `seedling` | `developer` | `human` | 🔁 changed |
| `guides/2026/2026-04-21-journeys.md` | `guides` → `explanation` | `seedling` | `developer`, `ops`, `security` | `human` | 🔁 changed |
| `guides/2026/2026-04-21-00-day-one.md` | `guides` → `explanation` | `seedling` | `developer`, `ops` | `human` | 🔁 changed |
| `guides/2026/2026-04-21-user-flow.md` | `guides` → `explanation` | `seedling` | `security` | `human` | 🔁 changed |
| `guides/2026/2026-04-21-design-system.md` | `guides` → `explanation` | `seedling` | `developer` | `human` | 🔁 changed |
| `guides/2026/2026-04-21-known-issues.md` | `guides` → `explanation` | `seedling` | `developer`, `ops` | `human` | 🔁 changed |
| `guides/2026/2026-04-21-testing.md` | `guides` → `explanation` | `seedling` | `developer`, `security` | `human` | 🔁 changed |
| `guides/2026/2026-04-21-adb-route-simulation.md` | `guides` → `explanation` | `seedling` | `developer` | `human` | 🔁 changed |
| `guides/2026/2026-04-21-security.md` | `guides` → `explanation` | `seedling` | `developer`, `ops`, `security` | `human` | 🔁 changed |
| `conventions/agentic-ai/96929-convention-entry-point-plugins-codebase-src-rust-src-main.rs.md` | `conventions` → `explanation` | `seedling` | `developer`, `security` | `human` | ✅ kept |
| `conventions/ai-architect-mcp/98818-convention-file-....md` | `conventions` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `conventions/agentic-ai/96911-convention-contributing_worktree_protocol.md.md` | `conventions` → `explanation` | `seedling` | `developer` | `human` | ✅ kept |
| `conventions/ai-architect-mcp/99082-convention-file-mcp-ai_architect_mcp-_adapters-github_adapter.py.md` | `conventions` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `conventions/cortex/97351-convention-file-mcp_server-tool_error_handler.py.md` | `conventions` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `conventions/ai-architect-mcp/99074-convention-file-mcp-ai_architect_mcp-_adapters-filesystem_adapter.py.md` | `conventions` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `conventions/ai-architect-mcp/99075-convention-file-mcp-ai_architect_mcp-_adapters-git_adapter.py.md` | `conventions` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `conventions/ai-architect-mcp/99073-convention-file-mcp-ai_architect_mcp-_adapters-composition_root.py.md` | `conventions` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `conventions/agentic-ai/97777-convention-file-packages-memory-__tests__-consolidation-stages-pruning.test.ts.md` | `conventions` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `conventions/agentic-ai/98265-convention-file-packages-memory-dashboard-src-db-init.ts.md` | `conventions` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `conventions/agentic-ai/98167-convention-file-packages-memory-src-shared-error-handler.ts.md` | `conventions` → `explanation` | `seedling` | `developer`, `ops` | `auto-generated` | ✅ kept |
| `conventions/ai-architect-mcp/99089-convention-file-mcp-ai_architect_mcp-_adapters-ports.py.md` | `conventions` → `explanation` | `seedling` | `developer`, `ops` | `auto-generated` | ✅ kept |
| `conventions/agentic-ai/86774-convention-p-align-center.md` | `conventions` → `explanation` | `seedling` | `developer`, `ops` | `human` | ✅ kept |
| `conventions/agentic-ai/96909-convention-p-align-center.md` | `conventions` → `explanation` | `seedling` | `developer`, `ops` | `human` | ✅ kept |
| `conventions/agentic-ai/97809-convention-file-packages-memory-__tests__-infrastructure-file-io.test.ts.md` | `conventions` → `explanation` | `seedling` | `developer`, `ops` | `auto-generated` | ✅ kept |
| `conventions/agentic-ai/86780-convention-phase_3_plan.md.md` | `conventions` → `explanation` | `seedling` | `developer`, `ops` | `human` | ✅ kept |
| `conventions/_general/2231-convention-research-post-context-assembly.md.md` | `conventions` → `explanation` | `seedling` | `developer`, `ops` | `human` | ✅ kept |
| `conventions/cortex/97311-convention-file-mcp_server-infrastructure-wiki_store.py.md` | `conventions` → `explanation` | `seedling` | `developer`, `ops` | `auto-generated` | ✅ kept |
| `conventions/cortex/97147-convention-file-mcp_server-core-workflow_graph_builder.py.md` | `conventions` → `explanation` | `seedling` | `developer`, `ops` | `auto-generated` | ✅ kept |
| `conventions/agentic-ai/97807-convention-file-packages-memory-__tests__-infrastructure-conversation-reader.tes.md` | `conventions` → `explanation` | `seedling` | `ops` | `auto-generated` | ✅ kept |
| `conventions/agentic-ai/86794-convention-entry-point-plugins-codebase-src-rust-src-main.rs.md` | `conventions` → `explanation` | `seedling` | `developer`, `security` | `human` | ✅ kept |
| `conventions/_general/2225-convention-cortex-methodology-agent.md` | `conventions` → `explanation` | `seedling` | `developer`, `ops`, `security` | `human` | ✅ kept |
| `conventions/agentic-ai/86779-convention-patterns.md.md` | `conventions` → `explanation` | `seedling` | `developer` | `human` | ✅ kept |
| `conventions/_general/2248-convention-ci-cd-.github-workflows-publish-ccplugins.yml.md` | `conventions` → `explanation` | `seedling` | `developer` | `human` | ✅ kept |
| `conventions/agentic-ai/98442-convention-file-packages-prd-pipeline-packages-ecosystem-adapters-src-contracts.md` | `conventions` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `conventions/ai-architect-mcp/99146-convention-file-mcp-ai_architect_mcp-_observability-file_adapter.py.md` | `conventions` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `conventions/cortex/97272-convention-file-mcp_server-infrastructure-file_io.py.md` | `conventions` → `explanation` | `seedling` | `developer`, `ops` | `auto-generated` | ✅ kept |
| `conventions/agentic-ai/96914-convention-patterns.md.md` | `conventions` → `explanation` | `seedling` | `developer` | `human` | ✅ kept |
| `conventions/ai-architect-mcp/98904-convention-file-....md` | `conventions` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `conventions/agentic-ai/96915-convention-phase_3_plan.md.md` | `conventions` → `explanation` | `seedling` | `developer`, `ops` | `human` | ✅ kept |
| `conventions/agentic-ai/97790-convention-file-packages-memory-__tests__-hooks-fixtures.ts.md` | `conventions` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `conventions/_general/1844-convention-dcp-wealth-android-day-one-checklist.md` | `conventions` → `explanation` | `seedling` | `developer` | `human` | ✅ kept |
| `conventions/agentic-ai/96936-convention-ci-cd-.github-workflows-ci.yml.md` | `conventions` → `explanation` | `seedling` | `developer`, `ops` | `human` | ✅ kept |
| `conventions/agentic-ai/97719-convention-file-packages-mcp-servers-memory-src-db-guard.ts.md` | `conventions` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `conventions/cortex/97268-convention-file-mcp_server-infrastructure-brain_index_store.py.md` | `conventions` → `explanation` | `seedling` | `developer`, `ops` | `auto-generated` | ✅ kept |
| `conventions/ai-architect-mcp/99083-convention-file-mcp-ai_architect_mcp-_adapters-local_audit.py.md` | `conventions` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `conventions/agentic-ai/96916-convention-phase_7_tracking.md.md` | `conventions` → `how-to` | `seedling` | `developer`, `ops` | `human` | 🔁 changed |
| `conventions/agentic-ai/98021-convention-file-packages-memory-src-import-scanner.ts.md` | `conventions` → `explanation` | `seedling` | `developer`, `ops` | `auto-generated` | ✅ kept |
| `conventions/dcp-wealth-android/64434-convention-pictet-wealth-app.md` | `conventions` → `explanation` | `seedling` | `developer` | `human` | ✅ kept |
| `conventions/ai-architect-mcp/99143-convention-file-mcp-ai_architect_mcp-_observability-composite_adapter.py.md` | `conventions` → `explanation` | `seedling` | `developer`, `ops` | `auto-generated` | ✅ kept |
| `conventions/agentic-ai/86781-convention-phase_7_tracking.md.md` | `conventions` → `how-to` | `seedling` | `developer`, `ops` | `human` | 🔁 changed |
| `conventions/agentic-ai/98234-convention-file-packages-memory-src-wiki-templates.ts.md` | `conventions` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `conventions/agentic-ai/97907-convention-file-packages-memory-__tests__-wiki-wiki-staleness.test.ts.md` | `conventions` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `conventions/agentic-ai/98360-convention-file-....md` | `conventions` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `conventions/agentic-ai/86801-convention-ci-cd-.github-workflows-ci.yml.md` | `conventions` → `explanation` | `seedling` | `developer`, `ops` | `human` | ✅ kept |
| `conventions/ai-architect-mcp/99125-convention-file-mcp-ai_architect_mcp-_interview-scorers-outline_flow.py.md` | `conventions` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `conventions/agentic-ai/98438-convention-file-....md` | `conventions` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `conventions/agentic-ai/98230-convention-file-packages-memory-src-wiki-storage-wiki-store.ts.md` | `conventions` → `explanation` | `seedling` | `developer`, `ops` | `auto-generated` | ✅ kept |
| `conventions/agentic-ai/86776-convention-contributing_worktree_protocol.md.md` | `conventions` → `explanation` | `seedling` | `developer` | `human` | ✅ kept |
| `conventions/_general/2233-convention-testing-guide.md.md` | `conventions` → `explanation` | `seedling` | `developer`, `ops` | `human` | ✅ kept |
| `conventions/agentic-ai/97773-convention-file-packages-memory-__tests__-consolidation-stages-compression.test..md` | `conventions` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `conventions/agentic-ai/98240-convention-file-packages-memory-src-workflow-graph-builder.ts.md` | `conventions` → `explanation` | `seedling` | `developer`, `ops` | `auto-generated` | ✅ kept |
| `conventions/agentic-ai/98031-convention-file-packages-memory-src-infrastructure-file-io.ts.md` | `conventions` → `explanation` | `seedling` | `developer`, `ops` | `auto-generated` | ✅ kept |
| `conventions/agentic-ai/98356-convention-file-....md` | `conventions` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `lessons/_general/2228-lesson-benchmarks-detail.md.md` | `lessons` → `how-to` | `seedling` | `developer` | `human` | 🔁 changed |
| `lessons/_general/1852-c1-plaintext-backbase-artifactory-credentials-in-git.md` | `lessons` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `lessons/2026/2026-04-17-cannot-be-set-in-sonar-project-properties.md` | `lessons` → `explanation` | `seedling` | `developer` | `human` | ✅ kept |
| `lessons/cortex/97525-lesson-file-tests_py-infrastructure-test_schema_integrity.py.md` | `lessons` → `explanation` | `seedling` | `developer`, `ops` | `auto-generated` | ✅ kept |
| `lessons/2026/2026-04-17-if-the-workflow-fails-on-either-publish-step-the-most-likely.md` | `lessons` → `explanation` | `seedling` | `developer` | `human` | ✅ kept |
| `lessons/2026/2026-04-17-known-issues-and-technical-debt-dcp-wealth-android.md` | `lessons` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `lessons/cortex/97502-lesson-file-tests_py-hooks-test_auto_recall.py.md` | `lessons` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `lessons/2026/2026-04-17-claims-from-prior-audits-that-were-falsified-have-been-remov.md` | `lessons` → `explanation` | `seedling` | `developer` | `human` | ✅ kept |
| `lessons/_general/1825-known-issues-and-technical-debt-dcp-wealth-android.md` | `lessons` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `lessons/2026/2026-04-17-c1-plaintext-backbase-artifactory-credentials-in-git.md` | `lessons` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `lessons/dcp-wealth-android/1224-tool-bash.md` | `lessons` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `lessons/2026/2026-04-17-tool-bash.md` | `lessons` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `lessons/_general/1855-known-issues-and-technical-debt-dcp-wealth-android.md` | `lessons` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `lessons/2026/2026-04-17-1-49-0.md` | `lessons` → `explanation` | `seedling` | `developer` | `human` | ✅ kept |
| `lessons/2026/2026-04-17-found-a-crash-when-coming-from-publication-push-notification.md` | `lessons` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `lessons/_general/1896-lesson-route-simulation-lessons-dcp-wealth-android.md` | `lessons` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `lessons/agentic-ai/86782-lesson-phase_plan.md.md` | `lessons` → `explanation` | `seedling` | `developer`, `ops` | `human` | ✅ kept |
| `lessons/2026/2026-04-17-known-issues.md` | `lessons` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `lessons/agentic-ai/96917-lesson-phase_plan.md.md` | `lessons` → `explanation` | `seedling` | `developer`, `ops` | `human` | ✅ kept |
| `lessons/cortex/97518-lesson-file-tests_py-infrastructure-test_pg_store_delete_by_tag.py.md` | `lessons` → `explanation` | `seedling` | `developer`, `ops` | `auto-generated` | ✅ kept |
| `lessons/2026/2026-04-21-route-simulation-findings.md` | `lessons` → `explanation` | `seedling` | `developer` | `human` | ✅ kept |
| `adrs/2026/2026-04-08-sonarcloud-analysis-via-sonarscanner-cli-not-the-sonarqube-g.md` | `adrs` → `adr` | `proposed` | `developer` | `human` | ✅ kept |
| `adrs/2026/2026-04-15-debug-keystore-jks-is-committed-despite-gitignore-policy-con.md` | `adrs` → `adr` | `proposed` | `security` | `human` | ✅ kept |
| `adrs/2026/2026-04-21-portfolio-details-declares-hilt-plugin-kapt-but-uses-ko.md` | `adrs` → `adr` | `proposed` | `developer` | `human` | ✅ kept |
| `adrs/2026/2026-04-15-backbase-and-new-fcm-pipelines-coexist-not-replaced.md` | `adrs` → `adr` | `proposed` | `developer`, `ops` | `human` | ✅ kept |
| `adrs/2026/2026-04-15-rotate-backbase-artifactory-credentials-committed-in-setting.md` | `adrs` → `adr` | `proposed` | `developer`, `ops` | `human` | ✅ kept |
| `adrs/2026/2026-04-08-manual-jacoco-agent-configuration-instead-of-the-jacoco-grad.md` | `adrs` → `adr` | `proposed` | `developer` | `human` | ✅ kept |
| `adrs/2026/2026-04-15-remove-committed-keystore-properties-and-debug-jks-from-git.md` | `adrs` → `adr` | `proposed` | `developer` | `human` | ✅ kept |
| `adrs/2026/2026-04-15-network-security-config-allows-cleartext-and-lacks-certifica.md` | `adrs` → `adr` | `proposed` | `developer` | `human` | ✅ kept |
| `adrs/2026/2026-04-15-maskingaction-only-masks-checkable-views-textview-pii-leaks.md` | `adrs` → `adr` | `proposed` | `developer` | `human` | ✅ kept |
| `adrs/2026/2026-04-15-myapplicationdependencies-is-a-1180-line-god-composition-roo.md` | `adrs` → `adr` | `proposed` | `developer`, `security` | `human` | ✅ kept |
| `adrs/2026/2026-04-17-adr-nnnn-slug-md-numbered-architecture-decision-records.md` | `adrs` → — | — | — | — | ❌ admission gate rejected (audit-tag, noise, or low score) |
| `adrs/2026/2026-04-08-author-the-wiki-as-a-first-class-layer.md` | `adrs` → `adr` | `proposed` | `developer` | `human` | ✅ kept |
| `adrs/2026/2026-04-15-domain-layer-currently-imports-android-util-log-and-android.md` | `adrs` → `adr` | `proposed` | `developer`, `ops` | `human` | ✅ kept |
| `adrs/2026/2026-04-15-sgn-credentials-shipped-in-apk-via-ci-sed-injection.md` | `adrs` → `adr` | `proposed` | `developer`, `security` | `human` | ✅ kept |
| `adrs/2026/2026-04-08-compose-ui-complexity-rules-excluded-via-journey-package-pat.md` | `adrs` → `adr` | `proposed` | `developer` | `human` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-src-prd-validator-rs-tests-test-regex-min-token-len.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-src-graph-store-rs-cypher-str.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-tests-fixtures-multilang-sample-rs-fetch-data.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-src-resolver-rs-resolve-graph.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-src-search-mod-rs-tests-test-term-score-contains-qn-only.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-src-parser-python-rs-tests-test-upper-snake-case.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-src-lsp-client-rs-path-to-file-uri.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-src-main-rs-do-extract-finding.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-src-stdlib-index-rs-get-stdlib-table.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-src-git-diff-rs-analyze-diff.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-src-resolver-layers-rs-run-macro-expansion.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-src-indexer-rs-tests-test-symlink-skipped.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-src-search-rrf-rs-tests-test-rrf-two-lists-fusion.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-src-search-vector-rs-query-index.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-src-semantic-diff-rs-tests-test-regression-score-dangl.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-src-parser-python-rs-tests-test-parse-simple-python.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-src-resolver-layers-rs-run-macro-expansion.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-src-lsp-resolver-rs-tests-test-find-node-at-position-n.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-src-prd-validator-rs-report-to-json.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-src-macro-expansion-rs-get-macro-table.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-src-indexer-rs-index-codebase-with-language.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-src-git-diff-rs-analyze-diff.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-src-graph-store-rs-is-known-rel-table.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-src-parser-rust-rs-tests-test-visibility-extraction.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-src-clustering-rs-tests-test-renumber-communities.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-tests-stage9-integration-rs-test-semantic-diff-detects-re.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-src-git-diff-rs-tests-test-git-ref-with-dash-rejected.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-src-main-rs-security-tests-test-health-check-tool-count-m.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-src-prd-input-rs-tests-test-load-verified-rejects-false-f.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-src-prd-input-rs-tests-test-tokenize-respects-max-toke.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-src-git-diff-rs-tests-test-parse-unified-diff-multiple.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-src-parser-typescript-rs-tests-test-typescript-imports.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-src-search-bm25-rs-build-schema.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-tests-stage4-integration-rs-test-prepare-prd-input-rej.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-src-main-rs-do-start-verification.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-tests-multilang-integration-rs-test-typescript-parser-.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-src-lsp-client-rs-tests-test-parse-definition-single-l.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-src-search-vector-rs-tests-test-sparse-cosine-orthogonal.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-tests-multilang-integration-rs-test-language-filter-ru.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-src-search-bm25-rs-tokenize-symbol.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-tests-fixtures-multilang-sample-rs-fetch-data.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-src-parser-python-rs-tests-test-parse-simple-python.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/parity-test-py-main.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-src-main-rs-do-analyze-codebase.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-tests-stage6-integration-rs-test-process-impact-contra.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-src-lsp-client-rs-detect-lsp-command.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-tests-stage3d-integration-rs-test-search-exact-name.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-src-semantic-diff-rs-tests-test-strongly-connected-cyc.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-src-main-rs-do-validate-prd-against-graph.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-src-prd-validator-rs-write-validation.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-src-main-rs-do-verify-semantic-diff.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-src-semantic-diff-rs-write-report.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-src-main-rs-do-get-processes.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-src-git-diff-rs-tests-test-parse-hunk-header.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-src-main-rs-do-query-graph.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-src-lsp-client-rs-validate-lsp-command.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-src-graph-store-rs-tests-test-cypher-str-escape-rules.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-src-prd-validator-rs-tests-test-compute-status-escalation.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-src-search-vector-rs-tests-test-tokenize-to-terms.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-src-parser-rust-rs-tests-test-parse-own-source.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-src-search-bm25-rs-build-index.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-src-search-rrf-rs-tests-test-rrf-disjoint-lists.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-tests-stage3b-integration-rs-test-resolution-pipeline.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-src-macro-expansion-rs-tests-test-rust-macro-count.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-src-semantic-diff-rs-tests-test-regression-score-cap.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-src-macro-expansion-rs-tests-test-derive-debug-impleme.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-src-parser-rust-rs-tests-test-all-construct-types.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-tests-stage3d-hybrid-search-rs-test-hybrid-semantic-searc.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-src-prd-input-rs-tests-test-tokenize-description-basic.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-src-parser-rust-rs-tests-test-visibility-extraction.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-src-search-bm25-rs-build-schema.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-tests-stage8-integration-rs-test-s3-public-api-warning.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/translations-pictet-babeledit-to-strings-py-main.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-src-prd-validator-rs-tests-test-looks-like-file-path.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-src-prd-input-rs-tests-test-clean-token-strips-punctuatio.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-reasoning-tools-memory-mcp-server-py-main.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-src-parser-typescript-rs-parse-typescript-file.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-tests-multilang-integration-rs-test-language-filter-rust-.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-src-indexer-rs-tests-test-symlink-skipped.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-src-clustering-rs-cluster-id-from-community-id.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-src-parser-python-rs-tests-test-upper-snake-case.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-src-search-bm25-rs-tokenize-symbol.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-src-semantic-diff-rs-tests-test-tarjan-detects-self-loop.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/99879-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-tests-stage9-integration-rs-test-semantic-diff-detects.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-src-parser-typescript-rs-parse-typescript-file.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-src-macro-expansion-rs-tests-test-lookup-println.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/99837-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-mcp/99043-file-ai-codebase-intelligence-tests-unit-test_heritage_mro.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/114243-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-mcp/98830-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/108512-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-mcp/99269-file-tests-test_prompting-test_metacognitive.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/114009-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-mcp/98960-file-....md` | `notes` → `explanation` | `seedling` | `developer`, `ops` | `auto-generated` | ✅ kept |
| `notes/ai-architect-mcp/99055-file-ai-codebase-intelligence-tests-unit-test_resolve_phase.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/103770-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-mcp/98911-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/97747-file-packages-memory-__tests__-automation-sync-instructions.test.ts.md` | `notes` → `explanation` | `seedling` | `developer`, `ops` | `auto-generated` | ✅ kept |
| `notes/ai-architect-mcp/98839-file-ai-codebase-intelligence-src-ai_codebase_intelligence-_config-models.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/cortex/97030-file-mcp_server-core-curation.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/103536-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/codebase-alteration-bench/2416-file-api-routes.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/110480-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/107237-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/114124-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/99869-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112102-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/101538-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112291-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113679-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/98605-file-plugins-codebase-src-rust-tests-scalability_bench.rs.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113651-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/codebase-alteration-bench/3300-file-models-session.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113998-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/97631-file-packages-codebase-__tests__-unit-adapter.test.ts.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/98453-file-packages-prd-pipeline-packages-mcp-server-src-context-budget.ts.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113152-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/cortex/97226-file-mcp_server-handlers-seed_project_constants.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/103093-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/cortex/96965-file-benchmarks-lib-noise_floor.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112313-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/codebase-alteration-bench/5844-file-api-routes.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/104621-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/108881-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/103147-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/108271-file-library-.build-checkouts-swift-crypto-sources-crypto-asn1-basic-asn1....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112598-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/109953-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/cortex/97422-file-tests_py-core-test_mmr_diversity.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/108944-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/105812-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/codebase-alteration-bench/2424-file-storage-user_repo.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/104788-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113942-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/108637-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/114001-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/98591-file-plugins-codebase-src-rust-src-search-rrf.rs.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-src-git-diff-rs-tests-test-parse-unified-diff-new-file.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/cortex/97087-file-mcp_server-core-query_decomposition.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/codebase-alteration-bench/9292-file-storage-user_repo.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/110833-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-mcp/98948-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/103634-file-....md` | `notes` → `explanation` | `seedling` | `developer`, `ops` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112285-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/108113-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112284-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113112-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/104241-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/98608-file-plugins-codebase-src-rust-tests-stage3b_v2_layers.rs.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113540-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-mcp/98973-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-src-lsp-client-rs-tests-test-parse-definition-null-res.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-mcp/98946-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/102773-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/101987-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/99938-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/codebase-alteration-bench/2408-file-auth-middleware.py.md` | `notes` → `explanation` | `seedling` | `developer`, `security` | `auto-generated` | ✅ kept |
| `notes/ai-architect/98721-file-ai-architect-ai-architect-presentation-viewmodels-dashboardviewmodel.swift.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/97774-file-packages-memory-__tests__-consolidation-stages-homeostatic.test.ts.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/108299-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/107475-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/codebase-alteration-bench/4150-file-storage-user_repo.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113078-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113002-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113542-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/codebase-alteration-bench/5016-file-storage-repository.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator-plugin-prooftesting/98622-file-mcp-server-index.js.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/cortex/97098-file-mcp_server-core-reranker_calibration.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-mcp/99110-file-mcp-ai_architect_mcp-_hooks-registry.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/103624-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/98257-file-packages-memory-dashboard-__tests__-dashboard-heat-decay.test.ts.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/102387-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/114007-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/108422-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/101732-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112042-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/109659-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/102048-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-src-stdlib-index-rs-get-stdlib-table.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/cortex/97417-file-tests_py-core-test_interference.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113674-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112778-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/98089-file-packages-memory-src-recall-handlers-memories-page.ts.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112481-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/codebase-alteration-bench/4978-file-auth-crypto.py.md` | `notes` → `explanation` | `seedling` | `developer`, `security` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/102367-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-src-semantic-diff-rs-tests-test-tarjan-detects-self-lo.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/97639-file-packages-codebase-src-internal-envelope.ts.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/cortex/97282-file-mcp_server-infrastructure-pg_store.py.md` | `notes` → `explanation` | `seedling` | `developer`, `ops` | `auto-generated` | ✅ kept |
| `notes/cortex/96972-file-benchmarks-llm_head_to_head-cortex_caller.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/codebase-alteration-bench/7553-file-models-session.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/104440-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/100299-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112303-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112988-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/103134-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/101557-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/100734-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/104302-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/98420-file-packages-prd-pipeline-packages-core-src-domain-hard-output-rule.ts.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/cortex/97185-file-mcp_server-handlers-detect_domain.py.md` | `notes` → `explanation` | `seedling` | `developer`, `ops` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113571-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/102143-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112263-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/101727-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/98049-file-packages-memory-src-methodology-handlers-detect-domain.ts.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/110853-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112614-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/99383-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/98063-file-packages-memory-src-methodology-style-classifier.ts.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112188-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/98189-file-packages-memory-src-wiki-claim-resolver.ts.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/97798-file-packages-memory-__tests__-import-backfill-memories.test.ts.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/103738-file-....md` | `notes` → `explanation` | `seedling` | `developer`, `security` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/102389-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/codebase-alteration-bench/7568-file-auth-token_service.py.md` | `notes` → `explanation` | `seedling` | `developer`, `security` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/101497-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113503-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112445-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/108535-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113019-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113254-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/102559-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-src-search-vector-rs-tests-test-sparse-cosine-identical.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/104278-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/101762-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/103829-file-....md` | `notes` → `explanation` | `seedling` | `developer`, `ops` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/104299-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/107827-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/98443-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/101882-file-....md` | `notes` → `explanation` | `seedling` | `developer`, `ops` | `auto-generated` | ✅ kept |
| `notes/cortex/97184-file-mcp_server-handlers-create_trigger.py.md` | `notes` → `explanation` | `seedling` | `developer`, `ops` | `auto-generated` | ✅ kept |
| `notes/ai-prd/107895-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/97694-file-packages-core-__tests__-codebase-port.test.ts.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113694-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect/98757-file-ai-architect-ai-architect-views-prd-clarificationpanel.swift.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-src-main-rs-security-tests-test-health-check-tool-coun.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect/98739-file-ai-architect-ai-architect-views-board-boardsidebarview.swift.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/codebase-alteration-bench/8432-file-models-session.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/102343-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/101551-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/104305-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/107624-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112734-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/108470-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112568-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113594-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/codebase-alteration-bench/10130-file-auth-crypto.py.md` | `notes` → `explanation` | `seedling` | `developer`, `security` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/97948-file-packages-memory-src-codebase-analysis-scanner-parse.ts.md` | `notes` → `explanation` | `seedling` | `developer`, `ops` | `auto-generated` | ✅ kept |
| `notes/ai-prd/107523-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/codebase-alteration-bench/6725-file-auth-middleware.py.md` | `notes` → `explanation` | `seedling` | `developer`, `security` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/111994-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/108983-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/codebase-alteration-bench/14000-file-auth-token_service.py.md` | `notes` → `explanation` | `seedling` | `developer`, `security` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113499-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/codebase-alteration-bench/6724-file-auth-crypto.py.md` | `notes` → `explanation` | `seedling` | `developer`, `security` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/86777-cutover_runbook.md.md` | `notes` → `runbook` | `seedling` | `ops` | `human` | 🔁 changed |
| `notes/ai-architect-prd-builder/100291-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/102110-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/101969-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/98333-file-packages-parity-runner-src-diff.ts.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/103021-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/103047-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/cortex/96994-file-mcp_server-core-ast_extractors.py.md` | `notes` → `explanation` | `seedling` | `developer`, `ops` | `auto-generated` | ✅ kept |
| `notes/cortex/97179-file-mcp_server-handlers-consolidation-memify.py.md` | `notes` → `explanation` | `seedling` | `developer`, `ops` | `auto-generated` | ✅ kept |
| `notes/ai-prd/107756-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/103437-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/codebase-alteration-bench/11016-file-storage-user_repo.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-mcp/99039-file-ai-codebase-intelligence-tests-unit-test_embeddings_integration.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/102489-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/108554-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/107555-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-src-stdlib-index-rs-tests-test-stdlib-table-size-rust.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/100451-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/97982-file-packages-memory-src-consolidation-stages-plasticity.ts.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112079-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113701-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/2026/2026-04-15-decision-created-2026-04-15t10-03-45z.md` | `notes` → `explanation` | `seedling` | `developer` | `human` | ✅ kept |
| `notes/ai-prd/106243-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/98251-file-packages-memory-src-workflow-graph-sources-source-ast.ts.md` | `notes` → `explanation` | `seedling` | `developer`, `ops` | `auto-generated` | ✅ kept |
| `notes/_general/1823-patterns-cheatsheet-dcp-wealth-android.md` | `notes` → `explanation` | `seedling` | `developer` | `human` | ✅ kept |
| `notes/ai-prd/107765-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/100321-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/104753-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112814-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/107387-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-mcp/99017-file-ai-codebase-intelligence-src-ai_codebase_intelligence-server-mcp_http.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113780-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112358-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/108297-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/108866-file-library-.build-checkouts-swift-nio-sources-nioposix-windows.swift.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112553-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/104426-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/101449-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/98576-file-plugins-codebase-src-rust-src-macro_expansion-rust.rs.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/105804-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/110999-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/102005-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112838-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112837-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113590-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/103694-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/cortex/97239-file-mcp_server-handlers-wiki_extract.py.md` | `notes` → `explanation` | `seedling` | `developer`, `ops` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/103483-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/104853-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-mcp/99157-file-mcp-ai_architect_mcp-_prompting-confidence_fusion.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112676-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112232-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/98212-file-packages-memory-src-wiki-handlers-wiki-reindex.ts.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-src-main-rs-do-get-context.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-src-security-gates-rs-check-gates.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/106249-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/101630-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113889-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/114097-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/107654-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/98523-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/cortex/97546-file-tests_py-shared-test_project_ids.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/107399-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/98085-file-packages-memory-src-recall-fractal-clustering.ts.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/100103-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112903-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/107997-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/101904-file-....md` | `notes` → `explanation` | `seedling` | `developer`, `ops`, `security` | `auto-generated` | ✅ kept |
| `notes/2026/2026-04-15-journeys-catalog-dcp-wealth-android.md` | `notes` → `explanation` | `seedling` | `developer` | `human` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-tests-stage3d-integration-rs-test-search-results-have-.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/99768-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112334-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/99901-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/104872-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/108638-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112409-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/cortex/97020-file-mcp_server-core-context_assembly-budget.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/97713-file-packages-mcp-servers-codebase-src-search.ts.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/97734-file-packages-mcp-servers-prd-src-build-conclude-opts.ts.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/104628-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/114132-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/97878-file-packages-memory-__tests__-remember-storage-pg-schema-tables.test.ts.md` | `notes` → `explanation` | `seedling` | `ops` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/102508-file-....md` | `notes` → `explanation` | `seedling` | `developer`, `ops` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112652-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/109492-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/108920-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/108162-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/108155-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112647-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/2026/2026-04-15-design-system-pictetds-dcp-wealth-android.md` | `notes` → `explanation` | `seedling` | `developer` | `human` | ✅ kept |
| `notes/ai-architect-mcp/98837-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/codebase-alteration-bench/9279-file-storage-repository.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/103642-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/108719-file-library-.build-checkouts-swift-nio-sources-nioechoserver-main.swift.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/98026-file-packages-memory-src-infrastructure-anthropic-llm-client.ts.md` | `notes` → `explanation` | `seedling` | `developer`, `ops` | `auto-generated` | ✅ kept |
| `notes/cortex/97263-file-mcp_server-hooks-session_lifecycle.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/cortex/97005-file-mcp_server-core-causal_graph.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112580-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113704-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/99806-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/104860-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/106878-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/109858-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-mcp/98903-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/codebase-alteration-bench/10146-file-models-session.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/codebase-alteration-bench/7551-file-auth-token_service.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-mcp/99129-file-mcp-ai_architect_mcp-_interview-scorers-success_metrics.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112467-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/101484-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/110656-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/cortex/97210-file-mcp_server-handlers-navigate_memory.py.md` | `notes` → `explanation` | `seedling` | `developer`, `ops` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/98364-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/codebase-alteration-bench/4153-file-auth-crypto.py.md` | `notes` → `explanation` | `seedling` | `developer`, `security` | `auto-generated` | ✅ kept |
| `notes/ai-architect-mcp/99122-file-mcp-ai_architect_mcp-_interview-scorers-clarity_level.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/109677-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-mcp/98968-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/99848-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/114225-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/108009-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113399-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/103027-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113015-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-src-git-diff-rs-tests-test-parse-hunk-header.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/104688-file-library-.build-checkouts-quick-sources-quick-quickmain.swift.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112635-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/codebase-alteration-bench/4127-file-storage-repository.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/98368-file-packages-prd-pipeline-packages-benchmark-calibration-__tests__-xmr.test.ts.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/109701-file-library-.build-checkouts-quick-sources-quick-async-asyncexamplegroup.swift.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113985-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/101362-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/98039-file-packages-memory-src-infrastructure-profile-store.ts.md` | `notes` → `explanation` | `seedling` | `developer`, `ops` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/114082-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/109506-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/103482-file-....md` | `notes` → `explanation` | `seedling` | `developer`, `ops` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/99913-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112522-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/108887-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/102578-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/98036-file-packages-memory-src-infrastructure-mcp-client.ts.md` | `notes` → `explanation` | `seedling` | `developer`, `ops` | `auto-generated` | ✅ kept |
| `notes/ai-prd/106960-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/99818-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/cortex/97436-file-tests_py-core-test_retrieval_dispatch.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113630-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/107590-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/98077-file-packages-memory-src-recall-context-assembly-budget.ts.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/104603-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112213-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/codebase-alteration-bench/15370-file-models-session.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/107649-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/99855-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/108702-file-library-.build-checkouts-swift-nio-sources-niocore-socketaddresses.swift.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-feedback-loop/98786-file-scripts-extract_contracts.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/98391-file-packages-prd-pipeline-packages-benchmark-calibration-mismatch-fire-rate.ts.md` | `notes` → `explanation` | `seedling` | `developer`, `ops` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-src-main-rs-do-get-processes.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-src-clustering-rs-trace-processes.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/99918-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/114185-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/codebase-alteration-bench/13995-file-auth-token_service.py.md` | `notes` → `explanation` | `seedling` | `developer`, `security` | `auto-generated` | ✅ kept |
| `notes/ai-prd/105830-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/cortex/97328-file-mcp_server-server-http_standalone_graph.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/100264-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/101516-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/98070-file-packages-memory-src-narrative-index.ts.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113650-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect/98743-file-ai-architect-ai-architect-views-board-iconsidebar.swift.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/codebase-alteration-bench/2414-file-storage-user_repo.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112098-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/102855-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/103643-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/100188-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/108735-file-library-.build-checkouts-swift-nio-sources-niofs-filehandleprotocol.swift.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113343-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/109361-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-tests-stage3c-integration-rs-test-clustering-and-proce.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/104797-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/107519-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/108654-file-library-.build-checkouts-swift-nio-sources-niocore-bytebuffer-hex.swift.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113034-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/103901-file-....md` | `notes` → `explanation` | `seedling` | `developer`, `ops` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/98123-file-packages-memory-src-recall-vector-similarity.ts.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/102757-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/codebase-alteration-bench/1571-file-api-routes.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113494-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/101447-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/108706-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112495-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/110479-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/104824-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/103844-file-....md` | `notes` → `explanation` | `seedling` | `developer`, `ops` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/109514-file-library-.build-checkouts-nimble-tests-nimbletests-statustest.swift.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/100800-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113052-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/114119-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113747-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-mcp/99130-file-mcp-ai_architect_mcp-_models-__init__.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113117-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112083-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112396-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-mcp/98893-file-ai-codebase-intelligence-src-ai_codebase_intelligence-_server_entry.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/cortex/97305-file-mcp_server-infrastructure-sqlite_store_entities.py.md` | `notes` → `explanation` | `seedling` | `developer`, `ops` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/104170-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/109797-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/99850-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/100395-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-src-prd-validator-rs-validate-prd.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/cortex/96963-file-benchmarks-lib-longitudinal_runner.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113144-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/cortex/97089-file-mcp_server-core-query_router.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/cortex/97365-file-scripts-test-agent-briefing.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/102179-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/109105-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/codebase-alteration-bench/13976-file-auth-crypto.py.md` | `notes` → `explanation` | `seedling` | `developer`, `security` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/98209-file-packages-memory-src-wiki-handlers-wiki-read.ts.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113250-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-mcp/98836-file-ai-codebase-intelligence-src-ai_codebase_intelligence-_config-__init__.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/codebase-alteration-bench/9281-file-auth-middleware.py.md` | `notes` → `explanation` | `seedling` | `developer`, `security` | `auto-generated` | ✅ kept |
| `notes/ai-architect-feedback-loop/98813-file-scripts-validate_prd_output.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113268-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/101587-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/98232-file-packages-memory-src-wiki-symbol-verify.ts.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/98186-file-packages-memory-src-shared-wiki-ir.ts.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/107622-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/102045-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/codebase-alteration-bench/4123-file-auth-token_service.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/111281-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112805-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113180-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/97869-file-packages-memory-__tests__-remember-handlers.test.ts.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/106930-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/108014-file-library-.build-checkouts-swift-collections-tests-heaptests-heaptests.swift.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/codebase-alteration-bench/12202-file-storage-user_repo.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/99341-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/108375-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/98125-file-packages-memory-src-remember-emotional-tagging.ts.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-mcp/98957-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/97979-file-packages-memory-src-consolidation-stages-decay.ts.md` | `notes` → `explanation` | `seedling` | `developer`, `ops` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113853-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/codebase-alteration-bench/6721-file-storage-user_repo.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113800-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-src-tool-schemas-rs-tools-list.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/99968-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/101613-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112763-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/100298-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/cortex/97262-file-mcp_server-hooks-preemptive_context.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/101315-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/cortex/97404-file-tests_py-core-test_emergence_tracker.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/107850-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113740-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/114057-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-mcp/99267-file-tests-test_prompting-test_confidence_fusion.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/107970-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/101612-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113696-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113012-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-tests-stage3d-hybrid-search-rs-test-rrf-fusion-combine.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/108761-file-library-.build-checkouts-swift-nio-sources-niofs-openoptions.swift.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/104234-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/codebase-alteration-bench/8410-file-models-session.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/111279-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/108361-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/107434-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/107945-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/97847-file-packages-memory-__tests__-recall-memories-page.test.ts.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/107952-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112603-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/103979-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/codebase-alteration-bench/2429-file-auth-crypto.py.md` | `notes` → `explanation` | `seedling` | `developer`, `security` | `auto-generated` | ✅ kept |
| `notes/cortex/97248-file-mcp_server-handlers-wiki_resolve.py.md` | `notes` → `explanation` | `seedling` | `developer`, `ops` | `auto-generated` | ✅ kept |
| `notes/codebase-alteration-bench/11013-file-models-session.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/104466-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113104-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/107483-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/102563-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-mcp/98965-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/103870-file-....md` | `notes` → `explanation` | `seedling` | `developer`, `ops` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112558-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-src-main-rs-do-get-symbol.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/108878-file-library-.build-checkouts-swift-nio-sources-nioudpechoclient-main.swift.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/102491-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113982-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/107848-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-mcp/98984-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/codebase-alteration-bench/8454-file-storage-repository.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-mcp/98951-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/cortex/97372-file-tests_py-benchmarks-test_beam_long_context_truncator.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/103120-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/107652-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-tests-stage4-integration-rs-test-prepare-prd-input-missin.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/codebase-alteration-bench/12186-file-auth-middleware.py.md` | `notes` → `explanation` | `seedling` | `developer`, `security` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/110867-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/codebase-alteration-bench/5856-file-api-routes.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113380-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/102358-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/102359-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/2026/2026-04-17-2-dev-null-grep-v-build-grep-domain-changed.md` | `notes` → `how-to` | `seedling` | `developer` | `human` | 🔁 changed |
| `notes/ai-prd-generator/113986-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-mcp/99292-file-tests-test_verification-test_consensus_router.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/103095-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/99797-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113814-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/114027-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/codebase-alteration-bench/12195-file-auth-crypto.py.md` | `notes` → `explanation` | `seedling` | `developer`, `security` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/99406-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/103143-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/102547-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/114181-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-src-parser-python-rs-tests-test-python-import-normaliz.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/codebase-alteration-bench/4138-file-storage-user_repo.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/109368-file-library-.build-checkouts-nimble-sources-nimble-dsl.swift.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/98502-file-packages-prd-pipeline-packages-validation-src-__tests__-validation.test.ts.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/103721-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112818-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/102709-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-mcp/98870-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/103076-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/108476-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/99805-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113298-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112095-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/101879-file-....md` | `notes` → `explanation` | `seedling` | `developer`, `ops` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/102569-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/codebase-alteration-bench/12174-file-api-routes.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/107831-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/codebase-alteration-bench/7555-file-storage-repository.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/cortex/97552-file-tests_py-test_doctor.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/114151-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113302-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/99304-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113824-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/codebase-alteration-bench/2433-file-models-session.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/cortex/97358-file-mcp_server-tool_registry_wiki.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/104206-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/99790-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/114245-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-src-security-gates-rs-tests-test-gates-passed-requires-ze.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/98126-file-packages-memory-src-remember-handlers-admission.ts.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-src-search-vector-rs-build-index.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/plugins-codebase-src-rust-src-clustering-rs-get-impact.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/101769-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/codebase-alteration-bench/9296-file-auth-middleware.py.md` | `notes` → `explanation` | `seedling` | `developer`, `security` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/100326-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/103884-file-....md` | `notes` → `explanation` | `seedling` | `developer`, `ops`, `security` | `auto-generated` | ✅ kept |
| `notes/ai-prd/104616-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/109640-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-mcp/98921-file-ai-codebase-intelligence-src-ai_codebase_intelligence-cli-serve.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112362-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/cortex/97394-file-tests_py-core-test_compression_encode_count.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/101533-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-src-lsp-client-rs-tests-test-lsp-graceful-fallback-on-fak.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/101815-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113943-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/98387-file-packages-prd-pipeline-packages-benchmark-calibration-index.ts.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/104624-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/agentic-ai/97796-file-packages-memory-__tests__-hooks-timeout.test.ts.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/104861-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/114244-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/109491-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/codebase-alteration-bench/9305-file-auth-crypto.py.md` | `notes` → `explanation` | `seedling` | `developer`, `security` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113179-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/103701-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/102435-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/114134-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113621-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `reference/codebase/packages-codebase-rust-tests-stage3b-v2-layers-rs-test-stdlib-resolution-push.md` | `reference` → `reference` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/106831-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/105829-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/111879-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/cortex/97476-file-tests_py-handlers-test_consolidate_telemetry.py.md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/101860-file-....md` | `notes` → `explanation` | `seedling` | `developer`, `ops` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/114043-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/102856-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/101572-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112951-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/103916-file-....md` | `notes` → `explanation` | `seedling` | `developer`, `ops` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/113834-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112045-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/114171-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/103716-file-....md` | `notes` → `explanation` | `seedling` | `developer`, `security` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112723-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/cortex/97170-file-mcp_server-handlers-codebase_analyze.py.md` | `notes` → `explanation` | `seedling` | `developer`, `ops` | `auto-generated` | ✅ kept |
| `notes/ai-prd/108534-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/101601-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd-generator/112728-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/104149-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/107877-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-architect-prd-builder/103436-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
| `notes/ai-prd/108795-file-....md` | `notes` → `explanation` | `seedling` | `developer` | `auto-generated` | ✅ kept |
