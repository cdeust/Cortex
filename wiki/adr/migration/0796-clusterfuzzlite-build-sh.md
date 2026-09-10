---
title: "ADR-0796 — .clusterfuzzlite/build.sh rationale"
status: accepted
source: .clusterfuzzlite/build.sh
---

# ADR-0796 — .clusterfuzzlite/build.sh

Source rationale preserved verbatim. Identifiers inside historical quotations are not current identities.

## .clusterfuzzlite/build.sh — original line 3

````text
#
# -e so a failed dependency install fails the build instead of producing a
# fuzzer that cannot import the code it is meant to exercise — a silently
# useless fuzzer is worse than none, because the dashboard turns green.
````

## .clusterfuzzlite/build.sh — original line 8

````text
# Runtime dependencies of the modules under test, hash-pinned from uv.lock
# (scripts/generate_pip_constraints.py). The harnesses import mcp_server
# modules, so their imports must resolve.
# --no-deps: the file is the complete, uv-resolved dependency graph — pip
# must install it as-is rather than re-deriving it from metadata, which
# breaks the moment pyproject.toml's [tool.uv] override-dependencies
# steers a package past a bound another package's metadata still declares
# (issue: PR #332, mpmath 1.4.1 vs sympy's `mpmath<1.4`).
````

## Final non-Python residual audit

### .clusterfuzzlite/build.sh — pre-cleanup line 25

````text
# Ship each harness's committed corpus as its seed corpus. These are the
# reproducers of bugs already found (see fuzz/corpus/*/repro-*) plus shape
# seeds; starting from them keeps the fuzzer from rediscovering the shallow
# surface on every run.
````
