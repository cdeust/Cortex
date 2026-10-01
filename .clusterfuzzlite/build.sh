#!/bin/bash -eu
# Build every fuzz/ harness into a libFuzzer binary.
# source: ADR-0796
#
#
#

# uv.lock's dev+sqlite set into the builder's own Python, hash-verified;
# --inexact keeps the atheris the base image ships. source: ADR-1092
UV_PROJECT_ENVIRONMENT="$(python3 -c 'import sys; print(sys.prefix)')" \
    uv sync --project "$SRC/cortex" --locked --inexact --no-cache \
    --no-install-project --no-default-groups --extra dev --extra sqlite
pip3 install --no-deps -e "$SRC/cortex"

# compile_python_fuzzer is provided by the base image. It wraps each harness
# with atheris's instrumentation and emits $OUT/<name>.
for harness in "$SRC"/cortex/fuzz/fuzz_*.py; do
    compile_python_fuzzer "$harness"
done

# Ship each harness corpus as its seed corpus.
# source: ADR-0796
for corpus in "$SRC"/cortex/fuzz/corpus/*/; do
    name="$(basename "$corpus")"
    if [ -d "$corpus" ]; then
        zip -j "$OUT/${name}_seed_corpus.zip" "$corpus"* >/dev/null
    fi
done
