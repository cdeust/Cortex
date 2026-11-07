# Final native review and local repair checks, 2026-10-28

Canonical source: commit 3ba69e01c5a04c128ab7c49e89beb7e2bf48048a from PR204. Discovery helper SHA256: a1e484a9e674f51971ecbaca87d99ca6dda94da2aa69569c513efedfa0077d16. CheckRun groups preserve duplicate gates and ignore StatusContext name collisions; full authenticated Pipeline proof remains the rerun authorizer. There is no new prerequisite veto. The test adapter uses the Cortex fixture namespace and its existing nullable-proof fixture.

Local commit 7c5b6fdf adds repair for eligible merge infrastructure failures and bounded private helper sessions. The actual owned-process probe and safety controls are documented in autopilot-merge-timeout-20261028.md. No installed service was changed during this patch.

Combined validation: 330 tests plus 399 subtests passed under pytest prepend in 8.88 seconds and importlib in 9.11 seconds. The CI default is prepend; importlib is an additional probe. Standard-library discovery passed 330 tests in 8.754 seconds. Ruff check/format, actual Cortex craftsmanship and whitespace checks passed.

This supersedes the discovery helper hashes and consumer counts in native-reconciliation-consumer-20261028.md, native-discovery-review-corrections-20261028.md and native-review-proof-first-20261028.md. Known per-PR NOT_FOUND errors are isolated; forbidden, rate-limited and unknown transport failures still stop hosted discovery conservatively. Hosted validation of the final published head remains pending.
