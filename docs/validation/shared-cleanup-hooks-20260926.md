# Shared cleanup verification, 2026-09-26

## Contract and provenance

The owner requested the existing shared Claude/Codex hook be packaged in Cortex,
with transcripts retained by default and deletion made explicit. The source is the
local `disk-hygiene` implementation exercised with Transartica draft
[PR 2](https://github.com/cdeust/transartica-remake/pull/2), head
`ccdf0f9c7b623027d337ca6c094e785308572680`. Its registered worktree and local branch
were removed after push. The remote PR and branch remained. That trial validates
the source hook; the candidate bundle has separate tests below.

The port keeps the original Git eligibility checks and host-specific file selectors.
Module splits satisfy Cortex's size limits. Added behavior is default transcript
retention, scoped startup recovery, retained branch retry, and lock-independent
session-end intake. Reader and root-scope fixes cover optional Claude deletion.

## Completion ledger

| Requirement | Evidence |
| --- | --- |
| A1: shared host entry and real Git disposal | `test_exact_manifest_command_accepts_native_payload`, `test_success_unmerged_branch_removed`, `test_success_without_upstream` |
| A2: empty startup, resume, duplicate ownership, repository boundaries | `test_start_outside_git_with_no_ended_records`, `test_resume_cancels_ended`, `test_unknown_and_other_owner`, `test_other_repository_ended_owner_retained` |
| A3: Git/process/evidence failure paths | `test_status_error`, `test_remove_error_no_fallback`, `test_unavailable_lsof_fails_closed`, `test_missing_or_changed_evidence` assert protected results and retained paths |
| A4: malformed registry, symlinks, deletion setting | `test_malformed_ledger_is_not_replaced`, `test_symlink_registration_refused`, `test_claude_symlink_ancestor_is_protected`, `test_invalid_opt_in_is_rejected_before_removal` |
| A5: partial removal retains branch retry | `test_pending_branch_retry_survives_ledger_reload`, `test_pending_branch_advanced_is_protected` |
| A6: retry and resumed-owner cancellation | `test_intake_startup_recovers_real_git_worktree_across_hosts`, `test_resume_consumes_old_marker_without_ending_current_owner`, `test_resume_cancels_pending_deletion`, `test_codex_same_session_different_roots_keeps_original_pending` |
| B1: lock ordering | Nonblocking registry locks; end intake uses unique files before any registry lock. Host cleanup runs after ownership lock release. External Git/lsof calls have bounded waits. `test_end_subprocess_completes_while_global_ledger_is_locked` |
| B2: concurrent events | Atomic file replacement and unique per-event paths; `test_later_end_survives_earlier_ack`, `test_worktree_ack_does_not_consume_host_event` |
| B3: interrupted/failed registry work | `test_invalid_ledger_does_not_lose_end_event`, `test_claude_interrupted_end_keeps_durable_pending`; intake is acknowledged only after durable consumer save. Git/filesystem/network operations are not a single atomic transaction; ownership must be respected by other processes. |
| C1: growth | Registry scans and pending-event scans are linear in registered paths/events; Git verification is per eligible worktree. No global cache/history scan. The original lsof recursive scan scales with the registered directory. |
| C2: resource lifetime | File/context managers, subprocess completion, temporary Git refs removed in finally; fixtures clean their repositories. Native probe processes exit and registered scratch is disposed after evidence preservation. |
| C3: runtime | Native timings and exact revision hashes recorded below; no retrieval algorithm change or retrieval benchmark claim. |
| D1: command/path injection | Git and gh use argv arrays; PR URL and UUID checks precede path building. `test_symlink_registration_refused`, `test_claude_symlink_ancestor_is_protected` |
| D2: mutable remote and local data | `test_live_remote_rewritten_behind_stale_tracking`, `test_remote_changes_between_checks`, `test_local_unpushed` |
| D3: access | No added secret material. Cleanup reads local artifacts and verifies the explicitly linked GitHub PR with existing user authentication. Privacy documentation describes requests. |
| E1: interface | Additive plugin hooks and documented CLI; transcript deletion changes from the local source's default to explicit opt-in. No published CLI is replaced. |
| E2: named consumers | Claude `.claude-plugin/plugin.json` and Codex `hooks/hooks.json`; exact command execution tests cover all four events for each host. |
| E3: persisted state | New plugin ledger is separate from the standalone ledger. Existing standalone tasks finish through their original command; no silent adoption. Unknown/corrupt records remain protected. |
| E4: platform | macOS native validation; Unix lsof is required. Missing lsof protects paths. Windows cleanup is not claimed as native-tested; the file-lock branch is platform-specific. |
| F1: diagnostics | JSON `protected` results tested for locks, dirty/ignored files, unknown owner, changed evidence and unavailable checks. Startup supplies ownership instructions through `hookSpecificOutput`. |
| F2: degraded behavior | No force-delete or filesystem fallback after Git failure: `test_remove_error_no_fallback`. Deferred cleanup remains in its ledger/intake. |
| G1: path coverage | Module/path mapping below covers dispatch, retention, retry, safety checks and error modes. |
| G2: regression sensitivity | Three focused injected mutants (default deletion, bypassed receipt, bypassed writer lock) each cause asserting tests to fail. These are targeted mutations, not an exhaustive mutation score. |
| G3: isolation | Real Git fixtures use isolated local remotes and fake GitHub metadata; native hooks use isolated cleanup storage. No test operates on another session's paths. |
| G4: negative assertions | Default transcript bytes remain; active owner/repository mismatches remain; dry-run performs no fetch/removal; writer locks protect files. |
| G5: validation | Full cleanup component suite plus adjacent session-queue and manifest contract tests; repository lint/format and craftsmanship checks. PostgreSQL is outside this stdlib component. |
| H1–H3: code quality | Repository craftsmanship, source checker, Ruff lint/format; independent safety review fixed end-intake contention and Claude transcript/root-scope findings. |
| H4: documentation | CHANGELOG, privacy, both plugin guides, disk-hygiene guide and ADR-1092 updated. |
| H5: commit scope | One focused cleanup feature commit; no global hook/trust changes or unrelated owner files. |
| H6: delivery | PR creation is authorized; merge/release is outside this task. CI status is reported on the pushed revision. |
| H7: observed defects | Review findings are fixed with tests in this change. |

## Code paths and asserting tests

| Module/path | Observable checks |
| --- | --- |
| `disk_hygiene.py`: CLI/event dispatch, invalid payload/identity, policy validation | Exact manifest contract and intake subprocess tests; transcript policy test |
| `cleanup_operations.py`: register/claim, PR linkage/evidence, dirty/ignored/unpushed/locked/main/unknown paths, dry-run, temp Git guard, worktree removal, branch retry | `test_worktree_cleanup.py` and `test_worktree_cleanup_lifecycle.py` |
| `cleanup_processes.py`: open files, no open files, unavailable process check | `test_active_file_prevents_removal`, `test_no_active_file_is_clear`, `test_unavailable_lsof_fails_closed` |
| `cleanup_registry.py`: invalid shape, atomic persistence, lock contention | `test_malformed_ledger_is_not_replaced`, intake lock subprocess test |
| `cleanup_intake.py`: durable end, independent consumers, later-event preservation, resumed owner, invalid ledger | `test_worktree_cleanup_intake.py` |
| `cleanup_hooks.py`: current owner, ended owner, cross-host/repository recovery, no eligible records, no Git cwd, temp scope | `test_worktree_cleanup_lifecycle.py` |
| `host_cleanup.py`: host dispatch, pending import, rooted retries, resume | `test_durable_host_end_recovers_on_next_start`, host contract and Claude scope tests |
| `session_purge.py`: retained/default/deleted main+nested transcripts, scratch, readers, scoped retry, symlinks | `test_cleanup_transcripts.py` and `test_cleanup_scoped_pending.py` |
| `codex_purge.py`: default retention, matching/fresh receipt, writer lock, no end-time sweep, deferred retry, resume | `test_cleanup_transcripts.py`, `test_cleanup_host_contract.py` |
| `transcript_policy.py`: keep/delete/invalid | Transcript policy and default-retention tests |
| Both manifests and existing module contract | `test_cleanup_host_contract.py`, `test_codex_plugin_hooks_contract.py` |

## Reproduction

```sh
python -m pytest tests_py/hooks/test_worktree_cleanup*.py tests_py/hooks/test_cleanup*.py tests_py/hooks/test_session_queue.py tests_py/scripts/test_codex_plugin_hooks_contract.py -q --no-cov
ruff check
ruff format --check
python scripts/check_craftsmanship.py --base origin/main
python scripts/check_project_wiki.py
```

## Measured results

The final cleanup component and adjacent contracts passed: **109 passed, zero
skipped**, in 48.51 seconds. The test bootstrap warned that the optional local
PostgreSQL database was unavailable; none of the selected tests was skipped.
Repository Ruff lint and format passed (1,565 Python files); craftsmanship,
project-wiki mirror, source-discipline and live marketplace-pin checks passed.

Targeted mutation probes killed all three injected defects: deletion enabled by
default (one test failed), receipt verification bypassed (one test failed), and
writer-lock protection bypassed (two parametrized tests failed). Source files were
not modified by these probes; each ran in a separate interpreter.

Native source Codex timings before packaging were SessionStart 0.114 s, Stop
0.087 s and SessionEnd 0.543 s. These are individual observations, not a benchmark
sample or a speedup claim. Native candidate dispatch observations and file hashes
are in [the native report](shared-cleanup-native-20260926.json). The transparent
PATH recorder forwarded the installed cleanup command to the candidate bundle
with isolated cleanup roots. This proves actual host dispatch and execution; it
does not prove installation or approval of a newly installed plugin. Global hooks
and trust settings were not changed. Both actual host transcripts still existed
after the probes; seeded resume fixtures were byte-identical.

The independent final code review approved the requested safety/contract scope
after the root-scope and interrupted-end fixes. The native reports record exact
candidate module hashes separately from the unit-test result.

| Final native host | SessionStart | Stop | SessionEnd | Hook exits |
| --- | ---: | ---: | ---: | --- |
| Codex 0.157.1 | 0.142 s | 0.094 s | 0.126 s | All observed hooks 0 |
| Claude Code 2.1.283 | 0.182 s | Not delivered | 0.125 s | Both observed hooks 0 |

Final observed event hashes match the committed bundle. Codex exited 0; Claude
exited 1 on API quota error 429. Earlier full Claude lifecycle results retain their
own revision hashes in the report. The final probe directory was disposed after
evidence preservation (16,139 bytes), with its ownership entry verified absent.

The bundled commit checker also passed after grouping existing purger arguments
into location tuples/options and extracting two small persistence/dispatch helpers.
The interface refactor preserves the shared engine; its 109-test rerun used the
normal project test bootstrap. The final malformed-ledger test formatting cleanup
passed its focused rerun. New prose passed the redaction check; the whole-file
scan reports advisory patterns in historical changelog/privacy text under the
existing permissive repository profile.

The final interface-only revision passed native Codex SessionStart/Stop/SessionEnd.
Claude delivered SessionStart and SessionEnd successfully but exited on its
external session rate limit before generation, so it did not deliver Stop.
The previous revision passed native Claude Stop; the final exact manifest Stop
command passes the isolated command test. The final Claude Stop native rerun is
unverified. No model/account change or rate-limit bypass was attempted.

## CI integration correction

Run 36257614026 at 3c359821 failed all five Linux test jobs on the same fourteen
failures: thirteen matcher/timing-aggregation tests rejected the standalone command,
and one package inventory test still expected only session_queue.py. The initial
109-test selection did not cover these two existing manifest consumers.

The correction recognizes the exact cleanup command in timing routes and requires
its measured sample; it does not omit cleanup costs. The package inventory now
lists the shared bundle explicitly and verifies imports stay within stdlib/bundle.
Regression tests preserve rejection of unknown/duplicate commands and missing
measurements while accepting historical snapshots that predate cleanup.

Correction verification used the normal project bootstrap:

```sh
python -m pytest tests_py/hooks tests_py/scripts -q --no-cov --basetemp REGISTERED_SCRATCH/expanded-tests
```

Result: 1,839 passed, 27 skipped, 378 subtests passed in 295.53 seconds. The
focused routing/package contracts passed with no skips. All three injected timing
mutations were detected: accepting duplicate hooks, accepting malformed cleanup
commands, and omitting required cleanup samples. Repository lint/format, both
craftsmanship checkers, source discipline and wiki mirrors passed. Peer review of
the package checks and parent review of the parser found no blocking issues.
Runtime cleanup scripts and their recorded native hashes are unchanged.
