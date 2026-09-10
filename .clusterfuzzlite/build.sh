#!/bin/bash -eu
# Build every fuzz/ harness into a libFuzzer binary.
# source: ADR-0796
#
#
#

# source: ADR-0796
#
#
#
#
#
#
#
pip3 install --no-deps --require-hashes -r "$SRC/cortex/requirements/ci-sqlite-min.txt"
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
