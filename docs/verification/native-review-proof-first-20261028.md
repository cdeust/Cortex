# Native review discovery corrections, 2026-10-28

Claude Opus 5.5 review6459888424 on Cortex816 identified repeated REST reads for incomplete native reviews and global starvation after a permanent per-PR API error.

The authenticated GraphQL review proof now precedes per-PR run/job reads. Incomplete reviews and unresolved proof after a successful review gate perform no REST run/job reads. Failed-test readiness repair remains eligible. A partial status rollup cannot veto full authenticated proof. Known per-PR HTTP404/GraphQL NOT_FOUND errors skip that PR; forbidden, rate-limited and unknown transport errors stop discovery without emitting a matrix. Diagnostics contain fixed categories only.

All four Codex completion jobs have a five-minute operational timeout, matching the existing fallback schedule period. Actual non-model jobs in run40626520816 took9s and11s; this cap is an operational choice, not a completion SLA. Only GitHub Actions issues reruns; the local daemon classifies repairs. No extra required review gate was added. The official Claude workflows select claude-opus-5-5 and each specialist inherits that model.

Canonical production assets were independently reviewed and passed the actual Cortex craftsmanship scanner. Runtime SHA256ab4956bfbbfd64c9b0c9774021120fefba90eaf0b0f919083537888ea776d74b; discovery SHA25677497df4ad82192074c68123e365e7a1f80430762c9840a5c0f3c61e1e015c21; Codex workflow SHA2563f6c9d7a58570ce410d794367ac9dfcfddfe68413d539c0e8a20e130cf59a1f6. Workflows were regenerated from the canonical template; ci.json bytes were preserved.

Consumer validation: Cortex315 tests plus399 subtests passed in actual pytest importlib mode;315 tests also passed via unittest. Spec107 native CI contracts passed. Ruff, actual Cortex craftsmanship and diff whitespace checks passed. Hosted execution of the final commits remains pending.

Sources: https://docs.github.com/en/rest/using-the-rest-api/troubleshooting-the-rest-api and https://docs.github.com/en/graphql/guides/using-pagination-in-the-graphql-api .
