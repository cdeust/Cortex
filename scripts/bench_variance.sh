#!/usr/bin/env bash
# Variance measurement for BEAM benchmark — clean cortex_bench per run.
# Usage: scripts/bench_variance.sh <label> <n_runs> [--assembler]
set -euo pipefail

LABEL="${1:?label required}"
N="${2:?n_runs required}"
MODE="${3:-}"

OUTDIR="benchmarks/beam/variance"
mkdir -p "$OUTDIR"

export DATABASE_URL="postgresql://localhost:5432/cortex_bench"

if [[ "$MODE" == "--assembler" ]]; then
    export CORTEX_USE_ASSEMBLER=1
    echo "Mode: assembler (3-phase structured context)"
else
    unset CORTEX_USE_ASSEMBLER || true
    echo "Mode: baseline (WRRF top-k)"
fi

for i in $(seq 1 "$N"); do
    OUT="$OUTDIR/${LABEL}_run${i}.txt"
    echo
    echo "════════════════════════════════════════════════"
    echo "Run $i/$N — $LABEL → $OUT"
    echo "════════════════════════════════════════════════"

    psql -h localhost -d postgres -c "DROP DATABASE IF EXISTS cortex_bench;" >/dev/null
    psql -h localhost -d postgres -c "CREATE DATABASE cortex_bench;" >/dev/null
    psql -h localhost -d cortex_bench -c "CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pg_trgm;" >/dev/null

    .venv/bin/python benchmarks/beam/run_benchmark.py --split 100K 2>&1 | tee "$OUT" | tail -25
done

echo
echo "All runs done. Outputs in $OUTDIR/"
