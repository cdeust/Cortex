# Issue #685: named degradation failures

The approved issue names remember dedup, SQLite recall signals, profile
freshness, and hot-memory retrieval. This revision follows the hosted unit
failures and Claude review on PR #819 at
`df3b1062008f59fe49a78123a3e6d09364ee8025`.

| Reference | Implementation | Result |
| --- | --- | --- |
| Dedup failure permits create | remember_helpers.try_curation | Search and merge failures propagate. |
| Lower-level SQLite vector failure | SqliteSearchMixin.search_vectors | Query failures propagate, including direct calls. |
| FTS signal disappears | SqliteSearchMixin._signal_fts | Query failures stop recall before partial fusion. |
| Vector signal disappears | SqliteRecallSignalsMixin._signal_vector | Already propagates under ADR-1109; regression retained. |
| Invalid freshness permits rebuild | rebuild_profiles._check_skip | Raises with force=true recovery guidance, including naive timestamps. |
| Hot-memory read becomes empty | query_methodology._get_hot_memories | Opened-store read failures propagate through the public handler. |
| Unread fallback counters | doctor._recorded_failures | Both backend lists expose component/count/last error as optional history. |
| Capture merge leaves a transaction | capture_store.store | Uses the same transaction scope as MCP tool calls. |

Symptom: dependency failures returned successful-looking fallback results.
Goal: named failures reach callers, while historical fallback counters are readable.
Scope: direct search_fts, store-open caching in _try_get_memory_store,
_get_fired_triggers, other fallback families, ranking algorithms, and
transaction atomicity across already committed merge steps remain outside #685.
The capture boundary rolls back unfinished writes; it does not undo prior commits.

The fallback recorder retains its ADR-0640 contract. Propagating paths no longer
call silent_failure.note or increment its fallback metric; existing handler
instrumentation reports tool errors. Tests assert these paths do not add
fallback entries. Historical counters never reset in production and do not
establish current health, so their diagnostic check is optional.
A separate doctor process has its own history.

## Hosted baseline and acceptance

GitHub-hosted unit job:
https://github.com/cdeust/Cortex/actions/runs/40643492447/job/122666895984

Raw baseline summary:
`4 failed, 11122 passed, 26 skipped, 2 warnings, 920 subtests passed in 649.73s`.

The four failures asserted superseded fallback behavior:
- test_rebuild_profiles.py: test_handles_invalid_updated_at_gracefully
- test_s110_sweep_handlers.py: test_malformed_timestamp_degrades_to_rebuild_and_is_logged
- test_s110_sweep_handlers.py: test_search_failure_degrades_to_create_and_is_logged
- test_s110_sweep_infrastructure.py: test_rrf_fts_signal_failure_degrades_and_is_logged

Those assertions now require visible errors. Additional hosted regression gates:
- The public remember handler's first vector lookup succeeds and its second
  (curation) lookup fails; the original error escapes, the insert boundary is
  untouched, and the real SQLite row count is unchanged.
- Direct search_vectors raises for a missing index and a misaligned buffer.
- A real capture merge fails after updating the row but before completing FTS;
  the original row survives, the connection is clean, and another writer commits.
- Malformed and naive timestamps stop before scan/save with force=true guidance.
- Both backend diagnostic lists expose lifetime history without blocking readiness.
- Hot-memory read failures reach the public handler across selection paths.

The missing-index try_curation test bypasses remember's earlier novelty lookup.
In the full remember handler a broken index can fail at that earlier lookup;
the second-call test isolates the later dedup boundary. Vector recall failures
and unreadable-profile failures already propagated on the inspected base.

Candidate sources remain GitHub API data only. No candidate source was checked
out, written to a local file, imported, or executed on the Mac.
All 15 changed Python payloads passed AST parsing and trusted Ruff format/lint
checks through stdin before publication.
The GitHub-hosted Pipeline executes ci.json's unit command and the regression,
e2e, environment, and install jobs. No passing result for this revision is
claimed before those jobs finish; the dispatcher owns subsequent CI events.

## Main synchronization

Preserve both histories with PR head first and main second:
main `36b6164b85e9e3256ff3993b96571582588c1001` adds #818, #820 and #821.
The combined doctor and changelog preserve those fixes and #685.
All other main changes use their exact Git blob receipts.
