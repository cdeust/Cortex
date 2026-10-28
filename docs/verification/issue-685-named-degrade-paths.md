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
transaction atomicity across already committed merge steps, and the existing
file_io.read_json policy (log unreadable/corrupt profiles and treat them as
absent) remain outside #685.
The capture boundary rolls back unfinished writes; it does not undo prior commits.

The fallback recorder retains its ADR-0640 contract. Propagating paths no longer
call silent_failure.note or increment its fallback metric; existing handler
instrumentation reports tool errors. The s110 regressions check the named
freshness, dedup, and recall-signal counters; test_named_degrade_paths_685 also checks
that injected failures leave fallback history empty. Historical counters never
reset in production and do not
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
  untouched (assert_not_called is the no-insert guard).
- Direct search_vectors raises for a missing index and a misaligned buffer.
- A stub handler calls the real update_memory_compression method and fails
  after updating the row but before completing FTS;
  the original row survives, the connection is clean, and another writer commits.
- Present but malformed or naive timestamps stop before scan/save with
  force=true guidance and the expected parsing/arithmetic exception type as cause.
- force=true bypasses that timestamp check; unrelated domain-shape errors
  retain their own exception rather than blaming updatedAt.
- A successful capture commits a real SQLite write visible from another handle.
- Both backend diagnostic lists expose lifetime history without blocking readiness.
- Hot-memory read failures reach the public handler across selection paths.

The missing-index try_curation test bypasses remember's earlier novelty lookup.
In the full remember handler a broken index can fail at that earlier lookup;
the second-call test isolates the later dedup boundary. Vector recall failures
already propagated on the inspected base. The former injected load_profiles
OSError case did not model real reads: file_io.read_json logs failures and
returns None, so corrupt index/domain files are treated as absent.

Candidate sources remain GitHub API data only. No candidate source was checked
out, written to a local file, imported, or executed on the Mac.
The previous 7018173 revision's 15 changed Python payloads passed AST parsing
and trusted Ruff format/lint checks through stdin before publication.
The GitHub-hosted Pipeline executes ci.json's unit command and the regression,
e2e, environment, and install jobs. No passing result for this revision is
claimed before those jobs finish; the dispatcher owns subsequent CI events.

## Main synchronization

Preserve both histories with PR head first and main second:
main `36b6164b85e9e3256ff3993b96571582588c1001` adds #818, #820 and #821.
The combined doctor and changelog preserve those fixes and #685.
All other main changes use their exact Git blob receipts.

## Hosted execution blocker on 7018173

Unit job: https://github.com/cdeust/Cortex/actions/runs/40653908988/job/122700281893

The runner was Ubuntu 26.04.1, image ubuntu26/20261012.163.
It failed before pytest while initializing the pinned PostgreSQL 18.6.0 archive:
`postgres: error while loading shared libraries: libxml2.so.2: cannot open shared object file`.

Ubuntu 26 provides [libxml2-16](https://packages.ubuntu.com/search?keywords=xml2&suite=resolute);
[Ubuntu's security package table](https://ubuntu.com/security/notices/USN-8787-1)
also identifies libxml2-16 for 26.04 and libxml2 for 24.04.
The failure is binary/runtime compatibility, not a pytest result.
A compatible PostgreSQL artifact or CI environment is required before this
revision's runtime behavior can be verified. No CI threshold or test is bypassed.

Codex code/security review on 7018173 completed without findings.
Claude re-review [6463844274](https://github.com/cdeust/Cortex/pull/819#issuecomment-6463844274)
reported no blocking findings and identified the read_json documentation mistake
corrected here, along with the narrowed timestamp boundary and test refinements.

This follow-up's seven changed Python payloads passed AST parsing and Ruff
format/lint checks through stdin; their original API text matches Git blob
hashes. Hosted runtime verification remains pending.

## Capture assertions and baseline follow-up

Claude review at 223d774 identified two capture assertions that accessed
in_transaction on the ThreadLocalSqliteConnection proxy, which has no such
property. They now inspect the registry's native connection instead.
The method exists in sqlite_connection_registry.py; the proxy is unchanged.

Three stale craftsmanship exemptions are removed: the observability imports
in rebuild_profiles and sqlite_store_search, and try_curation's method size.
Static AST inspection confirms the two imports are absent and the function
spans 36 lines by end_lineno - lineno, below the gate's 40-line method limit.
Removing these records tightens the baseline; no new exemption is added.

Current hosted setup failure:
https://github.com/cdeust/Cortex/actions/runs/40665507420/job/122738926769
The Ubuntu 26.04 runner again fails to load libxml2.so.2 before pytest starts.
The corrected assertions and complete craftsmanship gate need hosted execution.


## Review correction after b1dc390

Hosted unit setup still fails before pytest:
https://github.com/cdeust/Cortex/actions/runs/40666548227/job/122742464563
The PostgreSQL executable cannot load `libxml2.so.2` on the Ubuntu 26.04 runner.
This is not a test result; runtime verification remains blocked on runner compatibility.

The doctor vector check now delegates its store probe to a helper, preserving
package/interpreter diagnostics and store closure while bringing both functions
under METHOD_LINE_LIMIT. The existing vector-check tests are the hosted behavior
gate. Fallback diagnostic output uses the existing redact_text boundary from
doctor_mcp; a regression checks secret removal, component ordering, counts and
history preservation. The failed-capture regression now requires the original
connection to survive rollback, so replacing it cannot satisfy the assertion.

Sources were edited as API data only. Static syntax and method-span checks are
pre-publication checks, not runtime proof. The dispatcher owns hosted CI follow-up.
