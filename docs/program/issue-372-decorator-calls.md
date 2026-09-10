# Issue 372 — decorator call edges: completion ledger

Issue: https://github.com/cdeust/Cortex/issues/372

Decision: [ADR-1058](../../wiki/adr/cortex/1058-python-decorator-call-attribution.md).
Baseline: `d50105006586c4d4e8409d1b00820fb0447192ba`.

## Delivered behavior

Explicit Python decorator calls are attributed to the decorated function, method,
or class. Basenames, immediate-class method names, lexical traversal and stable
first-occurrence deduplication retain the existing conventions. Bare decorators
produce no implicit call edge. The explicit `decorated_definition` dispatch arm
remains and now passes decorator calls to its definition. No relation or storage
schema changes are required.

The tests cover bare, single, stacked, argument-call, async, method, class,
nested-class, duplicate, redefinition and sibling-scope cases. Existing function
body extraction is retained. As documented in ADR-1058, flat qualified names do
not model rebinding: a later undecorated class with the same name does not erase
an earlier class registration entry.

## Measured coverage

[Machine-readable fixture and results](issue-372-decorator-call-coverage.json)
record a real `parse_file_ast` → `build_resolved_call_edges` comparison. The
baseline extractor is loaded from the recorded Git revision while the candidate
uses the working source; the parser and resolver are the same in both runs.
The two existing body edges remain unchanged, and the candidate adds three
registration edges (function, class and method): **2 → 5 total edges**.
The JSON includes both source files, complete edge lists and the candidate
extractor SHA-256. This is deterministic static graph coverage, not a runtime,
latency or semantic retrieval benchmark.

## Verification

All commands ran in the isolated issue-372 worktree with its own Python
installation, SQLite test root and unavailable private PostgreSQL socket. Normal
repository conftest guards remained enabled.

| Check | Result |
| --- | --- |
| AST suites, local graph resolver and mutation-registry tests | 257 passed |
| Full test collection | 8,236 collected; no collection errors |
| Collected-count documentation and badge floor checks | Passed; no badge change needed |
| Scoped mutation runner, `ast_extractors.py` | 511 mutants: 488 killed; 23 registered equivalent/unreachable survivors; zero unregistered, timeout or unreached |
| Ruff 0.16.6 `check .` / `format --check .` | Passed; 3,256 files formatted correctly |
| Pyright 1.1.411, changed production module | Zero errors, warnings or information messages |
| actionlint 1.7.12 | Passed |
| uv 0.11.3 lock check and generated requirements check | Passed; 13 requirements files checked |
| Documentation claims, version surfaces and CI gate completeness | Passed |
| Craftsmanship, canonical wiki mirror and whitespace checks | Passed; no baseline increases |

The scoped runner used `scripts/mutation_check.sh`, the AST test files matching
`tests_py/core/test_ast_*.py`, and production target
`mcp_server/core/ast_extractors.py`. Its selected suites include the new
`test_ast_decorator_calls.py` cases. Both decorator dispatch mutants (current
mutant IDs 27 and 28) were killed. Two old pending dispatch exemptions and a
now-killed fallback exemption were removed. One pre-existing unreachable
fallback exemption was renumbered from 39 to 57 after verifying the exact
mutation diff; no new exemptions were added. A direct callee-deduplication test
also kills the survivor that the combined decorator/body deduplication initially
masked.

The 23 accepted survivors consist of ten equivalent-by-construction and thirteen
unreachable-branch cases. This is a scoped mutation result, not a claim that all
possible program mutants were killed. Full test execution was not repeated for
this change; the full collection and focused executable suites are distinguished
above.

## Downstream boundary

`FileAnalysis.calls_per_function` and `build_resolved_call_edges` expose the
improved local graph after reparsing. The helper accepts class callers and
resolves known target basenames, but no current production caller of that helper
was found. `codebase_analyze` persists definitions, imports and inheritance, not
this call map. `ingest_codebase` consumes the external AP graph through
`ensure_graph` and `iter_call_edges`; wiki reference summaries are also upstream.
Those paths do not gain decorator edges from this local extractor change alone.
