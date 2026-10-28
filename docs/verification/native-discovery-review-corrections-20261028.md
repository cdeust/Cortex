# Native discovery review corrections, 2026-10-28

Historical receipt. Current behavior, hashes and tests are recorded in native-check-groups-cortex-20261028.md.

Native Claude reviews on Cortex816 comment6458968789 and Codebase466 comment6458952553 identified redundant per-PR REST work, a prerequisite filter that excluded legitimate readiness repair, and missing CLI boundary evidence.

Discovery now requests paginated PR/head/statusCheckRollup data with one GraphQL query. Drafts, forks, holds, active native gate checks and completed checks with no relevant review wait are eliminated before per-PR REST reads. GraphQL connection pages use the documented maximum of 100 nodes. Truncated status contexts conservatively proceed to full proof. The rollup is an optimization; existing authenticated _plan remains the only rerun authorizer, including readiness repair after failed tests. latest() performs the live PR read once. A repository concurrency group serializes discovery.

An API failure, including rate exhaustion, immediately terminates the scan without producing a matrix. Protocol errors on an individual PR remain isolated. Output-write errors have the output diagnostic. Worker grammar and environment checks run without reading or posting when invalid. No model runs or additional merge gates are introduced.

Evidence: the new contracts produced 12 failures against the previous helper, then passed with the correction. Canonical native contracts: 77 PASS. Targeted renderer/native tests: 52 PASS plus 33 subtests. Codebase actual ci.json Codex glob: 96 PASS. Cortex Ruff profile, actionlint and actual regression shell syntax pass. Draft/fork/hold/native-gate-inflight/green fixtures each perform one GraphQL discovery request and zero REST requests. External WAITING and FAILURE checks cannot veto a valid Pipeline plan; those regressions also execute the exact merge-job21 rerun. The positive repair fixture fails a unit job and emits only the existing authorized review-job20 rerun. A real subprocess CalledProcessError becomes EvidenceError(api) and stops after one request. The exact GraphQL query was accepted by GitHub and returned three open Codebase PRs in its first page.

Sources: https://docs.github.com/en/graphql/guides/using-pagination-in-the-graphql-api and https://docs.github.com/en/graphql/reference/objects#statuscheckrollup . The fallback still executes trusted main helpers; hosted acceptance depends on merging the correction and observing real scheduled or dispatched runs.

Consumer gate correction: generic source craftsmanship did not enforce the Cortex method cap. Extracted cohesive _page_nodes validation; root independently ran the actual Cortex craftsmanship_rules.scan_source on the final helper and both scheduled test files and obtained empty violation lists. Final helper SHA256 013cbb5510abd2999cff40102c12f93fbe95a6f8264295b2422be65a525e0029.

Published: canonical PR201 aaf31d377e0b17731b54211883654a6553e2f42a; Codebase466 366e8964991263764d5a87dd180e2df148dfe6d1. Remote API heads exactly match local commits. Root explicitly approved final helper after actual Cortex scanner validation.
