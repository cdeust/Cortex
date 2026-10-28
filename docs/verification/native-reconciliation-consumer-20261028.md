# Native reconciliation integration, 2026-10-28

Canonical source: https://github.com/cdeust/zetetic-team-subagents/pull/201 at aaf31d377e0b17731b54211883654a6553e2f42a. Production helper SHA256: 013cbb5510abd2999cff40102c12f93fbe95a6f8264295b2422be65a525e0029. Codex.yml SHA256: 618af59bff999194ff3950df13587eea8b8b1354aa059a971e9dfeb51078b6d1. Both consumer files match those bytes.

The GraphQL prefilter avoids per-PR REST reads for irrelevant candidates. Existing authenticated full proof remains the only rerun authorizer. API failures stop discovery; protocol failures are isolated per PR. Discovery and rerun jobs have their respective concurrency groups. No model calls or merge gates are added.

Cortex: 301 local CI Python contracts pass after integration. Actionlint and source/craftsmanship checks pass. Cortex uses its actual project scanner; test imports differ only for its tests_py/scripts layout. The detailed receipt records failed-test readiness repair and external-check regressions. Hosted fallback acceptance follows installation on main.
