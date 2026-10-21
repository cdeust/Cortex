---
created: 2026-10-13T14:41:37Z
kind: adr
number: 1101
status: accepted
tags: [windows, bash, tests, issue-689]
title: Resolve bash to an absolute Git Bash path and refuse the WSL launcher stubs
---
# ADR-1101: Resolve bash to an absolute Git Bash path and refuse the WSL launcher stubs

## Status

accepted

## Context

Issue #689: on Windows, `subprocess` resolves a bare `bash` through the CreateProcess search order, which tries `C:\Windows\System32` before PATH. With WSL enabled, that finds the WSL launcher stub instead of Git Bash; without a distribution the stub prints "Windows Subsystem for Linux has no installed distributions". A full-suite run on windows-latest on 2026-10-10 (run 38008915302, diagnostics run 38012683041) measured the effect: putting Git Bash first on PATH fixed 1 test, renaming the System32 launcher fixed 31 more, and 11 still failed because `where bash` listed a second stub under `WindowsApps`. A WSL bash with a distribution installed runs, but drops environment variables not listed in `WSLENV`, so probing the binary would accept the wrong bash.

Nine test files and `benchmarks/reranker_matrix/matrix.py` spawned a bare `bash` (inventory: full suite on macOS with a logging `bash` shim first on PATH, 2026-10-13). Two of the test files skipped when `shutil.which("bash")` was None, which hid the gap on a machine without bash.

A reviewer measured a stock Windows 11 machine on 2026-10-13 (Git for Windows, no WSL): the persistent PATH holds `C:\Program Files\Git\cmd`, which has `git.exe` but no `bash.exe`. Inside Claude Code, bash resolves to `Git\usr\bin\bash.exe` because Claude Code runs hooks through its own Git Bash; a process started elsewhere finds no bash on PATH.

The owner decided the product stance on 2026-10-13: WSL is the recommended way to run Cortex on Windows; native Windows with Git for Windows stays supported, and bash is a requirement there.

## Decision

1. One function resolves bash: `mcp_server.shared.platform.resolve_bash`. It returns an absolute path, which callers put in argv[0] so that CreateProcess never searches System32 first.
2. On Windows it walks PATH for `bash.exe` and refuses any candidate whose parent directories include `System32`, `Sysnative`, `SysWOW64` or `WindowsApps` (the WSL launcher stubs). It refuses by location, not by running the binary.
3. When PATH holds no usable bash, it derives `<git root>\bin\bash.exe` from a `git.exe` on PATH, up to two parents above it (`cmd\`, `bin\`, `mingw64\bin\`). Owner decision 2026-10-13, so that a stock Git for Windows install is found.
4. When nothing usable is found it raises `BashNotFoundError`, naming Git for Windows, WSL as the recommended setup, and the stubs it skipped. Callers never skip on a missing bash.
5. Every caller that spawns bash from Python goes through it: the ten test files (the nine of the inventory and `test_pgvector_action_retry_timeout.py` from PR #712), `benchmarks/reranker_matrix/matrix.py`, and the multi-bash parametrisations of issue #690, which keep `/bin/bash` and replace `shutil.which("bash")`.
6. The Windows CI job (`windows-latest`, SQLite) runs, with `pytest`: the resolver tests (`tests_py/shared/test_bash_resolution.py`) and the four migrated callers with no failure in the diagnostics run (`test_bench_regression_datasets.py`, `test_reproduce_only_validation.py`, `test_reranker_matrix_runner.py`, `test_setup_py_failure_message.py`; 0 failures each in windows-latest run 38012683041, variant D: WSL launcher renamed, Git Bash first on PATH, `PYTHONUTF8=1`; the job sets no `PYTHONUTF8`, so its first run is the isolating measurement). The other migrated callers still failed in variant D for the causes tracked in issue #692 and join the job as that issue clears them. Two PowerShell steps run with bash gone from PATH: one proves that `resolve_bash` raises `BashNotFoundError` naming Git for Windows while the WSL stubs stay reachable; the other removes every PATH directory that holds a `bash.exe` (Git for Windows and the stubs) and runs each hook command of `.claude-plugin/plugin.json`, which must fail with PowerShell's command-not-found error naming `bash`, never succeeding (owner decision 2026-10-13).

## Consequences

Positive: on Windows a test or benchmark either runs Git Bash or fails with a message that says what to install; the WSL stub can no longer be picked silently, and a machine without bash no longer passes by skipping.

Negative and known limits: the plugin hook commands in `.claude-plugin/plugin.json` still start with a bare `bash -c`; they rely on Claude Code running hooks through its own Git Bash and do not go through this resolver. Their only guarantee, enforced by the CI step of decision 6, is that they fail with a command-not-found error naming `bash` when no bash is on PATH; that error does not name Git for Windows. `#!/usr/bin/env bash` stubs written by tests run inside the resolved bash, so they inherit its PATH. Commands nested inside a bash script (`run_setup_py bash -c ...`) resolve through that bash, not through this function.
