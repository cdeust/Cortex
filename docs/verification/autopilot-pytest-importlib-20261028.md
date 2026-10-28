# Actual pytest collection and helper-failure correction

Base: PR #816 head 199d87761c46fa80bd6fce508ebf122d6f0bcbac.
Hosted failure: run 40626121228, job 122611400630.
Follow-up review: https://github.com/cdeust/Cortex/pull/816#issuecomment-6459888424

## Collection failure

The earlier standard-library unittest run did not reproduce the CI import mode.
Actual pytest with --import-mode=importlib reproduced four collection errors:
issue editors/pages/titles imported test_ci_autopilot_issues as a bare peer, and
review reconciliation imported test_ci_autopilot as a bare peer. The nested
rename-fixture import had the same defect. All five now use tests_py.scripts.*.
No test-directory sys.path workaround was introduced.

The read-only existing toolchain was Python 3.13.7 with pytest 9.1.1. Reproduction
and final command, run from the registered PR worktree:

```sh
/Users/cdeust/Developments/anthropic-partnership/Cortex/.venv/bin/python -B -m pytest --import-mode=importlib --noconftest -o addopts='' -p no:cacheprovider tests_py/scripts/test_ci_*.py -q --tb=short
```

The four original modules failed collection before the fix. After all changes,
304 tests and 399 subtests passed in 7.66 seconds. The standard-library CI suites
also passed all 304 tests in 8.12 seconds. The focused autopilot pytest suite
passed 77 tests and 51 subtests. --noconftest avoids production database setup;
this is the CI-script subset, not the full Cortex application suite.

## Per-PR failures

A real child Python TypeError previously escaped reconcile as CalledProcessError.
Spawn errors, empty/malformed JSON and invalid response contracts also stopped
the queue. They now return explicit helper_failure with a fixed environment or
protocol category and, for a child exit, its numeric exit_code. Raw stderr is
never copied into diagnostics. Unknown categories are rejected as contract
failures rather than silently treated as valid evidence.

Regressions prove later authorized work proceeds and accepted worker settlement
survives each failure. An inconsistent repair/error response cannot start a
model for the failed PR. Direct programming errors inside check/main still
raise visibly. No gate rerun, model or service installation was performed.

## Existing gh authentication

Only presence booleans were inspected: GH_TOKEN and GITHUB_TOKEN were absent in
both the service plist and the current environment. The shared reader argument
parser does not require either variable, and its API adapter invokes gh.
The installed -I helper test now explicitly removes both variables and still
performs its expected fixture GET. No parser change, token extraction, export or
hosted reader relaxation was needed. Live launchd acceptance remains separate.

Ruff check/format, the actual Cortex 300/40 craftsmanship gate and diff checks
passed. The shared environment and protected earlier worktree were preserved.
