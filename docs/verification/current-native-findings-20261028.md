# Current native security findings, 2026-10-28

Source: genuine Codex review https://github.com/cdeust/ai-architect-mcp-codebase/pull/464#discussion_r4395405890 on da7ad02db35b63d2b04eccf0dc84f848211c6915.

The regression fixture uses a summary announcing current finding22 and retained historical thread11; these are synthetic IDs from the bot reproduction. The old exact-set comparison rejected the combined set even when22 was resolved by the trusted owner. Seven regression subcases reproduced that protocol error before the correction.

The runtime now requires all current announced IDs to exist, evaluates resolution only for those IDs and returns only those IDs in its receipt. Current unresolved findings still block. Missing current IDs cannot be replaced by historical threads. Bot identity, owner resolution, repository/PR/head binding and pagination validation remain in force.

The source runtime and its embedded review-job copy have matching bytes. `source.json` classifies both as adaptations, preserving their original SHA256 and recording their new SHA256. The six Anthropic command/reviewer Markdown files remain verbatim; Opus5.5, native App authentication and locked CLI installations are unchanged. The legacy renderer remains unchanged.

Verification:

- Codebase existing CI regression entry point:15 unittest tests pass. Its imported contract contributes8 focused test methods, including resolved, unresolved and untrusted historical threads, missing current IDs, unresolved current findings, forged signers and malformed evidence.
- Canonical CI contracts:435 pytest tests and13 subtests pass in17.79s.
- The native renderer verifies script/embedded runtime equality and both original/adapted provenance digests; actionlint checks rendered workflows.

Corrected runtime SHA256: `dfaa509b48136801cfebf8bf6aacf7abf53fd2f537fa5a01cfd8eebaf1dd60bd`.

This is a CI-evidence correction. It does not claim hosted acceptance, resolve PR discussion threads or alter application code.

Cortex propagation: 224 CI unit tests pass, including the eight current-finding contracts. The Windows CLI resolver correction is separately covered by 19 tests and 10 subtests; native Windows acceptance remains pending.
