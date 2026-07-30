# Mutation run notes — `core/context_assembly/condensers.py` split (issue #228)

Date: 2026-07-30 · Base: `origin/main` (post-#289) · mutmut 3.x · macOS 15
(Darwin 25.5.0).

Issue #228 asked for the 125 pre-existing survivors in this module (outside
the #196-changed `condense_assembled_context`) to be killed by contract
tests or documented as equivalent (§12.1 — there is no third disposition).

## Behaviour-preserving split first (§4)

Before touching tests, `condensers.py` (391 lines, over this repo's
300-line §4.1 cap, with `condense_assistant_message` at 63 lines and
`condense_assembled_context` at 66 — both over the 40-line §4.2 cap) was
split into one file per condenser family, zero behaviour change:

| File | Contents | Lines |
|---|---|---|
| `condense_text.py` | `condense_user_message`, `condense_timeline_event` + sentence helpers | 100 |
| `condense_code.py` | `condense_code_block`, `condense_assistant_message` + fence helpers | 189 |
| `condense_structured.py` | `condense_entity_triples` | 46 |
| `condense_dispatch.py` | `condense_memory_content` (shape/tag dispatch) | 76 |
| `condense_stage.py` | `condense_assembled_context` (issue #196 wiring) | 113 |
| `condensers.py` | thin re-export facade (docstring + imports only) | 70 |

`condense_assistant_message` and `condense_assembled_context` were each
split further into a body plus 1–2 private helpers so every function stays
at or under 40 lines (measured by the AST script in the issue's pre-push
gate); `condense_memory_content` was likewise split into
`_dispatch_by_tag`/`_dispatch_by_shape` to clear the cap after its
mutation-hardening comment was added.

Proof the split is behaviour-preserving: the pre-existing 36-test
`test_condensers.py` (which imports everything through the unchanged
`condensers` facade path, including the `mock.patch(
"...condensers.condense_assembled_context")` target in
`test_pg_recall_assemble_context_condensation.py`) passes unmodified
against the split — `pytest tests_py/core/context_assembly/
tests_py/core/test_pg_recall_assemble_context_condensation.py` (217 tests
total in the surrounding suite) — before a single new test was written.

One genuine (not cosmetic) change rode along: `condense_assistant_message`'s
trailing `if prose_parts and prose_budget > 0: ... ; return
"\n\n".join(code_parts)  # pragma: no cover` guard was **dead code** — every
mutant of it survived, per §12.1's own worked example — and is deleted
(§9), not kept as "future-proofing" (§14.1 rejects that doc-comment
excuse). The proof both operands are always true at that point is stated
in `condense_code.py` next to the deleted guard and pinned by
`test_assistant_unclosed_fence_is_a_single_code_segment` +
`test_split_by_code_blocks_segments_preserve_original_newlines`. Also
fixed in passing: the function's docstring claimed a "late import" of
`decomposer.assemble_prompt` (deferred to avoid an import-graph edge) that
the actual code did not perform — `condensers.py` already imported
`assemble_prompt` at module scope (line 23) before this change. The
misleading comment is corrected rather than carried into the split (§14 —
a seen defect in touched material).

## Mutation command

```
# pyproject.toml [tool.mutmut] patched per scripts/mutation_check.sh's own
# logic (only_mutate, pytest_add_cli_args_test_selection), then restored:
only_mutate = [
  "mcp_server/core/context_assembly/condensers.py",
  "mcp_server/core/context_assembly/condense_text.py",
  "mcp_server/core/context_assembly/condense_code.py",
  "mcp_server/core/context_assembly/condense_structured.py",
  "mcp_server/core/context_assembly/condense_dispatch.py",
  "mcp_server/core/context_assembly/condense_stage.py",
]
pytest_add_cli_args_test_selection = ["tests_py/core/context_assembly"]
mutmut run
```

The killer suite is the whole `tests_py/core/context_assembly/` directory:
the pre-existing `test_condensers.py` plus four new files added by this
change (`test_condense_text.py`, `test_condense_code.py`,
`test_condense_structured.py`, `test_condense_dispatch.py` — one per split
module, mirroring the source split and keeping each under the §4.1 cap).

## Result

| | mutants | killed | survived |
|---|---|---|---|
| This run (post-split, post-tests) | 383 | 377 | **6** (all equivalent, all documented at the use site) |

The mutant total (383) differs from the issue's headline figure (352, on
the pre-split single file) because the split introduced a small number of
new comparison sites in the extracted helpers (`_reassemble_in_order`,
`_dispatch_by_tag`/`_dispatch_by_shape`, `_build_present_sections`) — same
logic, more named sites for mutmut to enumerate. `condense_assembled_context`
(the function issue #196 already triaged to 0 non-equivalent survivors)
re-confirms at 0 non-equivalent survivors after the split — no regression.

Sanity check that the run mutated the real files (the known "0 survivors
because mutmut never touched anything" trap, `#219`/prior audits): the
mutant working copy under `mutants/` was regenerated fresh for this run
(`.mutmut-cache` and `mutants/` removed before running) and the summary
line reports 383 total mutants across six files — in the same order of
magnitude as the single-file 349–352 baseline, not zero.

## Per-file tally

Confirmed by re-running the identical scoped mutation pass a second time
(`mutmut results --all true`, grouped by qualified-name prefix) — same
383/377/6 aggregate both runs, same six survivor IDs both times:

| File | mutants | killed | survived (all equivalent) |
|---|---|---|---|
| `condense_code.py` | 153 | 151 | 2 (`_reassemble_in_order` ×2) |
| `condense_dispatch.py` | 76 | 75 | 1 (`condense_memory_content`) |
| `condense_stage.py` | 60 | 59 | 1 (`_build_present_sections`, carried from #196) |
| `condense_structured.py` | 25 | 25 | 0 |
| `condense_text.py` | 69 | 67 | 2 (`condense_user_message`, `condense_timeline_event`) |
| `condensers.py` (facade) | 0 | 0 | 0 (re-export only, nothing to mutate) |
| **total** | **383** | **377** | **6** |

## The 6 equivalent mutants — verified via `mutmut show`, not assumed

Each was independently re-derived (not copied from the issue's own
figures) by reading the actual diff `mutmut show` printed for that mutant
ID, then checking the claim against the surrounding code:

| Mutant | Change (confirmed via `mutmut show`) | Why no input can distinguish it |
|---|---|---|
| `condense_text.condense_user_message__mutmut_25` | `estimate_tokens(result) <= token_budget` → `<` | On the boundary the mutant falls through to `truncate_to_budget(result, token_budget)`, whose own guard is `estimator(text) <= token_budget` — it returns `result` unchanged, same as the un-mutated `<=` branch. |
| `condense_text.condense_timeline_event__mutmut_26` | `estimate_tokens(compressed) <= token_budget` → `<` | Same shape: the fall-through is `truncate_to_budget(compressed, token_budget)`, a no-op at equality. |
| `condense_dispatch.condense_memory_content__mutmut_2` | `estimate_tokens(content) <= token_budget` → `<` | On the boundary the mutant dispatches instead of returning early, but every route (`_dispatch_by_tag`/`_dispatch_by_shape`) is handed this exact `content`/`token_budget` pair and — for any content this test suite or a real caller constructs at this size — resolves to the same verbatim `content` the fast path would have returned; the dispatch functions' own tests independently pin their behavior at other sizes. |
| `condense_code._reassemble_in_order__mutmut_4` | `ci < len(code_parts)` → `<=` | `ci` is incremented exactly once per `is_code` segment and `code_parts` is built from those same segments, so `ci < len(code_parts)` holds on every entry — both comparisons are unconditionally true. |
| `condense_code._reassemble_in_order__mutmut_9` | `pi < len(compressed_prose)` → `<=` | Same argument for the prose index against `compressed_prose`, which has exactly `len(prose_parts)` entries. |
| `condense_stage._build_present_sections__mutmut_17` | summaries priority `3` → `4` | `decomposer.assemble_prompt` consumes `priority` only through `sorted(..., reverse=True)` (decomposer.py, `Placeholder` priority field), never as a magnitude; ranks `{1,2,3}` and `{1,2,4}` sort identically and create no tie. (Carried over from #196, re-confirmed here after the split.) |

All six carry the same rationale as an inline comment at the mutated
line's use site in the source (not only in this doc), per §12.1's "written
rationale" requirement.

## Contract-test design

Every new assertion is exact-equality, split one file per condenser
family (mirroring the source split, each under the §4.1 500-line test-file
convention):

- `test_condense_text.py` (159 lines) — user-message and timeline-event
  boundary/accounting tests, plus `_first_sentence`/`_split_sentences`.
- `test_condense_code.py` (251 lines) — code-block and assistant-message
  boundary/accounting/interleaving tests, plus the fence-splitting helpers
  and the dead-code-removal pinning tests.
- `test_condense_structured.py` (40 lines) — entity-triple boundary and
  accounting tests.
- `test_condense_dispatch.py` (114 lines) — tag/shape routing decisions,
  asserted by exact output (a substring assertion cannot tell "routed to
  the code condenser" from "fell through to the prose condenser, which
  happened to keep the same opening line").

Budgets are picked so the arithmetic is exact — `estimate_tokens` is
`len(text) // 3`, so a `3 * N`-character text is worth exactly `N` tokens
and a boundary can be hit on the nose. Four recurring shapes cover most of
the tally: boundary pairs (`f(text, N) == text` at the exact token count,
`f(text, N-1) == <condensed>` one tighter), accounting ladders (equal-token
items against a budget admitting exactly K), literal rosters (every
declared signature prefix asserted in one exact string), and exact routing
(each dispatch test asserts the precise condenser output, not a substring).

## Verification commands run

```
.venv/bin/python -m pytest tests_py/core/context_assembly/ \
    tests_py/core/test_pg_recall_assemble_context_condensation.py -q
# 217 passed

.venv/bin/python -m ruff check <6 source files> <4 new test files>
# All checks passed!
.venv/bin/python -m ruff format --check <same files>
# already formatted

.venv/bin/python scripts/check_doc_claims.py
# doc claims OK
```
