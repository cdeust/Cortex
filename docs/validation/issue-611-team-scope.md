# Issue 611: scope repair validation and operator procedure

Base: `24c68c4a` (v4.23.0). Measured 2026-09-17.
Decision: ADR-1083, proposed for owner review. This change is not released.

## Regression evidence

The original `remember` regression failed because an agent decision returned
`is_global=True`. After separating the flags, the affected PostgreSQL suite
passes 182 tests. SQLite passes 175 tests, with seven PostgreSQL-only tests
skipped. The sandbox-only SQLite run reports PostgreSQL unavailable; the
PostgreSQL execution uses a separately created scratch database. The
reclassification script suite additionally passes 24 tests on PostgreSQL,
including transaction failure and archive validation paths.

Independent review reproduced an ingestion privilege regression: an `auto`
write was persisted as `deliberate`, and initialization then granted team
visibility. Four of eight origin/class reopen cases failed before persisting
the class. All eight pass after the fix on both backends. SQLite also tests
an upgrade from the old schema. The PostgreSQL upgrade was exercised on a
full restore of the pre-change production archive, including the existing
`current_memories` view.

## Production snapshot experiment

The custom-format production archive was restored in full into an isolated
PostgreSQL database; `pg_restore` exited zero. Production was not reclassified.
The script also checks for memories table data and decodes the full archive
before allowing PostgreSQL apply. This validates readability, not that an
arbitrary supplied archive belongs to the selected database; the operator
must create and retain the target's own backup as below.

| Measurement | Result |
| --- | --- |
| Current non-benchmark global candidates | 160 |
| Dry-run changes | 98 |
| Applied changes on the restored copy | 98 |
| Changes proposed on the second run | 0 |
| Retained globals | 62 |
| Retained globals with unresolved project | 47 |
| Total rows before and after repair | 47,490 |

All fields other than `is_global`, `is_team_decision`, and `directory_context`
had identical ordered aggregate hashes before and after repair:
`f66cfb02e0c7996857ccfe74b311e667`. This includes content, IDs, and supersession.
The comparison ran before the acceptance hooks, which can record receipts.

## Approved mapping and remaining owner decisions

All 47 originally empty `directory_context` rows also had an empty `domain`.
On 2026-09-17 the owner explicitly approved assigning memory 4353879 to
`/Users/cdeust/Developments/japonais-2027`. The operator input is a mappings
file of the form `{"domains": {}, "memories": {"<id>": "<project root>"},
"keep_global_ids": []}`. It names rows of one private store, so it is kept
outside the repository.

Applied to the already reclassified snapshot, this changes one additional
row to `is_global=false`, `is_team_decision=true`, with the approved directory.
The next pass changes zero rows. Across both passes, 99 of the original 160
candidates lose global scope; 61 remain global, including 46 unresolved rows.
The actual auto-recall launcher now excludes the Score audit decision from
anthropic-partnership and includes it in japonais-2027. Both processes exit
zero. This verifies the specific 4353879 acceptance signal on the snapshot.

Production remains unreclassified pending deployment of the reviewed code.
The parent Team Decisions query still returns unresolved row 4356519, whose
project requires separate owner review. The full SessionStart launcher
validation timed out after 60 seconds; direct query and subprocess fixture
tests do not replace final installed-plugin acceptance.

Remaining unresolved IDs, left global without changing their project:

4254394, 4342464, 4343116, 4347543, 4349020, 4349043, 4349560, 4349960, 4349976, 4350007, 4351552, 4351562, 4351771, 4352557, 4352618, 4353539, 4353601, 4353612, 4354421, 4354708, 4355514, 4355539, 4355775, 4356057, 4356262, 4356365, 4356519, 4356548, 4356730, 4357099, 4359407, 4359553, 4359753, 4359754, 4359755, 4359773, 4360000, 4361139, 4362817, 4365424, 4365650, 4367130, 4367241, 4367268, 4367557, 4367684

The legacy row does not store whether `is_global` was explicit or inferred.
Use `keep_global_ids` for rows independently known to have been explicitly
global. The script otherwise applies the existing content detector exactly
as requested by the reclassification plan.

## Operator procedure

1. Review ADR-1083 and the unresolved ID list. Start with the approved mapping
   file described above. Additional mappings require owner approval. Use a private file
   with verified `domains` and approved `memories` (decimal ID keys) maps
   to existing canonical absolute project directories, plus `keep_global_ids`.
   Empty mapping keys and inferred ownership from prose are rejected.
2. Deploy the reviewed code and schema before production reclassification.
   Old installations still run the team-to-global backfill at initialization
   and can reverse a data-only repair. Do not mix the repaired data with old
   writers. The owner controls merge, release and installed-plugin updates.
3. Create a fresh `pg_dump -Fc -f cortex-before-611.dump cortex`. Restore it
   to a separate scratch database and verify successful completion.
4. Run the script with the explicit target and inspect its JSON report:

   ```sh
   python scripts/reclassify_team_scope.py --database-url postgresql:///cortex \
     --mappings /private/path/scope-mappings.json
   ```

5. Apply that reviewed mapping with `--apply --backup /private/path/cortex-before-611.dump`.
   Repeat the dry-run and require `change_count: 0`. Preserve the reports and
   backup outside Git. SQLite uses `--sqlite-path` instead of `--database-url`.
6. Run both acceptance hooks from the updated installed plugin. Require
   4353879 absent in anthropic-partnership and present in japonais-2027, and
   no japonais-2027 row in the parent's Team Decisions block. Do not claim
   the issue fixed in a release or publish the LinkedIn draft before this.

## Python compatibility

CI Python 3.10 exposed a collection error from importing `typing.Self`, which
is unavailable in that supported version. The database context manager now
uses its concrete class as a postponed return annotation, with no new dependency.

## Completion ledger

| Changed behavior or failure path | Evidence |
| --- | --- |
| Separate global resolution and team classification | core global-scope and handler team-scope regressions |
| Trusted ingest class/origin survives reopening | eight-case matrix, both backends |
| Persist marker and upgrade existing schema/view | SQLite schema-upgrade test; restored PostgreSQL archive |
| Initialization does not promote team rows to global | backfill tests, including zero second-run row count |
| Session hooks enforce project predicate before limit | team-project hook tests and real subprocess tests |
| Agent briefing scopes both selection passes | PostgreSQL team-project regression |
| Explicit global and detector behavior preserved | global detector tests and cross-project hook fixtures |
| Domain mapping, approved ID mapping, unresolved rows | script classifier and mapping validation tests |
| Dry-run, second-run idempotence, history/benchmark exclusion | SQLite script tests and restored snapshot experiment |
| Transaction rollback and marker refusal | real PostgreSQL and SQLite script tests |
| Missing/invalid backup, missing table data, full decode | script backup validation tests and full archive restore |

No merge, release, production reclassification, LinkedIn publication, or
message to Denis is performed by this change. Task B is a separate session.
