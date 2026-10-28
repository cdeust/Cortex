---
created: 2026-10-27
kind: adr
number: 1101
status: accepted
tags: [windows, bash, issue-689]
title: Resolve bash to an absolute Git Bash path and refuse the WSL launcher stubs
---
# ADR-1101: Resolve bash to an absolute Git Bash path and refuse the WSL launcher stubs

## Context

[Issue #689](https://github.com/cdeust/Cortex/issues/689) and [the preserved PR738](https://github.com/cdeust/Cortex/pull/738) record the Windows shell failure and the owner decision to use Git Bash for native Windows. Main at 8b00ded3 still spawns a bare `bash` from the reranker matrix and shell tests. The original proposal also changed `ci.yml`, which main has removed.

## Decision

Resolve the shell to an absolute executable before spawning it. On Windows, reject candidates under System32, Sysnative, SysWOW64 and WindowsApps, where the WSL launchers reside. If PATH contains only `git.exe`, inspect its first three parents for `bin/bash.exe`, covering Git for Windows layouts with git.exe under cmd, bin or mingw64/bin. These layouts and the refusal contract are retained from PR738; `tests_py/shared/test_bash_resolution.py` exercises them without executing a stub.

A missing usable shell raises `BashNotFoundError` with installation guidance. The reranker matrix and the surviving shell callers from the original inventory use the resolver. The existing Pipeline environment command executes the resolved binary on Linux, macOS and Windows; no retired workflow is restored.

## Consequences

The resolver does not select a WSL distribution as a native Windows shell. The local fixtures validate candidate selection; successful native execution still depends on the current hosted environment job. Plugin manifest shell commands remain governed by the host's own hook launcher.
