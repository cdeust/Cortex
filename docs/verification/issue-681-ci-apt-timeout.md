# Issue 681 verification

The shared test-suite action bounds each pgvector `apt-get` command with
`timeout`, retries exit status 124, and reports whether update or install
timed out after the retry loop.

## External regression gate

Running the two regression checks against the fetched `origin/main` action
produced the expected failures:

```text
FAIL (expected on origin/main): test_pgvector_apt_attempts_are_bounded_and_report_timeout: AssertionError
FAIL (expected on origin/main): test_timeout_retries_each_command_and_names_final_failure: ValueError
```

On the changed action, the focused pytest result was:

```text
..                                                                       [100%]
2 passed in 0.53s
```

The shell test substitutes an apt command that returns GNU `timeout`'s
documented timeout status. It confirms each command is attempted three times
and its final diagnostic names the timed out command.

## Repository gates

On the final change:

```text
ruff format --no-cache --check .       1623 files already formatted
ruff check --no-cache .                All checks passed!
actionlint -color                      passed
pyright mcp_server/                    0 errors, 0 warnings, 0 informations
scripts/check_craftsmanship.py         Craftsmanship gate: OK
scripts/check_project_wiki.py          Project wiki mirrors match their canonical sources.
scripts/check_no_deps_invariant.py     no-deps-invariant gate: clean (126 file(s) scanned).
```

The final full CI pytest invocation completed with `9422 passed, 19 skipped,
185 failed, 373 subtests passed`. The failures are codebase and AST tests that
cannot load the local `tree_sitter_language_pack` native grammar libraries;
the reported error is `DynamicLoadError` while loading
`libtree_sitter_python.dylib`. The focused regression tests passed in the same
environment.
