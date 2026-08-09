#!/usr/bin/env bash
# Trust-factor calibration sweep (issue #368).
#
# Pre-registration, decision rule and grid: docs/provenance/trust-factor-calibration.md
# Read it before changing anything here — the grid is derived from a cheap
# adversarial sweep, and the decision rule is fixed in advance on purpose.
#
#   benchmarks/trust_factor_sweep.sh              # full grid, all three suites
#   benchmarks/trust_factor_sweep.sh --quick      # smoke the plumbing (NOT gated)
#
# One reproduce.sh invocation per cell, strictly SEQUENTIAL, each against its
# own ephemeral container. No parallelism: a fan-out on this machine on
# 2026-08-08 drove load to 37 and swapped 11.9 GB. Cells are independent, so a
# failed cell does not invalidate the others — it is reported and the sweep
# continues, because a partial grid with an honest gap beats a grid that
# silently stopped early.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || exit 1

# source: docs/provenance/trust-factor-calibration.md §Grid — brackets the
# 0.8 -> 0.7 transition found by the adversarial pre-sweep. 1.0 is the control.
GRID=(1.0 0.8 0.7 0.6 0.5)

EXTRA_ARGS=()
[[ "${1:-}" == "--quick" ]] && EXTRA_ARGS+=(--quick)

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUT_ROOT="benchmarks/results/trust-factor-sweep/${STAMP}"
mkdir -p "$OUT_ROOT"

LOG="${OUT_ROOT}/sweep.log"
echo "trust-factor sweep ${STAMP}" | tee "$LOG"
echo "grid: ${GRID[*]}" | tee -a "$LOG"
echo "pre-registration: docs/provenance/trust-factor-calibration.md" | tee -a "$LOG"

for W in "${GRID[@]}"; do
    CELL_DIR="${OUT_ROOT}/cell_W${W}"
    mkdir -p "$CELL_DIR"
    echo "" | tee -a "$LOG"
    echo "=== cell W=${W} — started $(date -u +%H:%M:%SZ) ===" | tee -a "$LOG"

    # Exported, not inlined: reproduce.sh spawns the benchmark processes, and
    # retrieval_dispatch.py reads the value at import in each of them.
    CORTEX_UNTRUSTED_ORIGIN_FACTOR="$W" \
        benchmarks/reproduce.sh \
        --only longmemeval,locomo,beam \
        --no-ablation \
        "${EXTRA_ARGS[@]}" \
        >"${CELL_DIR}/reproduce.log" 2>&1
    rc=$?

    if [[ $rc -eq 0 ]]; then
        echo "cell W=${W}: OK" | tee -a "$LOG"
    else
        # Not fatal to the sweep: an unusable cell is a gap in the grid, and
        # the decision rule can still be applied to the cells that reported.
        echo "cell W=${W}: FAILED rc=${rc} (see ${CELL_DIR}/reproduce.log)" | tee -a "$LOG"
    fi

    # reproduce.sh writes into benchmarks/results/repro/<its own stamp>/;
    # record which one belongs to this cell so the summary can be rebuilt
    # without guessing from timestamps.
    latest_repro="$(ls -td benchmarks/results/repro/*/ 2>/dev/null | head -1)"
    echo "${latest_repro}" > "${CELL_DIR}/repro_dir.txt"
    echo "cell W=${W} results: ${latest_repro}" | tee -a "$LOG"
done

echo "" | tee -a "$LOG"
echo "sweep finished $(date -u +%Y-%m-%dT%H:%M:%SZ) — results under ${OUT_ROOT}" | tee -a "$LOG"
echo "NEXT: apply the decision rule from the pre-registration and record the" | tee -a "$LOG"
echo "chosen W in docs/provenance/trust-factor-calibration.md §Results." | tee -a "$LOG"
