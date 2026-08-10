#!/bin/bash -eu
# Build every fuzz/ harness into a libFuzzer binary.
#
# -e so a failed dependency install fails the build instead of producing a
# fuzzer that cannot import the code it is meant to exercise — a silently
# useless fuzzer is worse than none, because the dashboard turns green.

# Runtime dependencies of the modules under test, hash-pinned from uv.lock
# (scripts/generate_pip_constraints.py). The harnesses import mcp_server
# modules, so their imports must resolve.
# --no-deps: the file is the complete, uv-resolved dependency graph — pip
# must install it as-is rather than re-deriving it from metadata, which
# breaks the moment pyproject.toml's [tool.uv] override-dependencies
# steers a package past a bound another package's metadata still declares
# (issue: PR #332, mpmath 1.4.1 vs sympy's `mpmath<1.4`).
pip3 install --no-deps --require-hashes -r "$SRC/cortex/requirements/ci-sqlite-min.txt"
pip3 install --no-deps -e "$SRC/cortex"

# compile_python_fuzzer is provided by the base image. It wraps each harness
# with atheris's instrumentation and emits $OUT/<name>.
for harness in "$SRC"/cortex/fuzz/fuzz_*.py; do
    compile_python_fuzzer "$harness"
done

# Ship each harness's committed corpus as its seed corpus. These are the
# reproducers of bugs already found (see fuzz/corpus/*/repro-*) plus shape
# seeds; starting from them keeps the fuzzer from rediscovering the shallow
# surface on every run.
for corpus in "$SRC"/cortex/fuzz/corpus/*/; do
    name="$(basename "$corpus")"
    if [ -d "$corpus" ]; then
        zip -j "$OUT/${name}_seed_corpus.zip" "$corpus"* >/dev/null
    fi
done
