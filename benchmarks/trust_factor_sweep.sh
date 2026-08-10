#!/usr/bin/env bash
# Trust-factor calibration sweep (issue #368).
#
# Pre-registration, decision rule and grid: docs/provenance/trust-factor-calibration.md
# Read it before changing anything here — the grid is derived from a cheap
# adversarial sweep, and the decision rule is fixed in advance on purpose.
#
#   benchmarks/trust_factor_sweep.sh              # run ONE pending cell, then exit
#   benchmarks/trust_factor_sweep.sh --quick      # smoke the plumbing (NOT gated)
#
# 2026-08-10 architecture change: this script used to loop over the whole
# grid in one process. Five campaigns died mid-grid over one session, each
# attributed to a different cause after the fact (contention, a native
# crash, a missing dataset, a session gap, a noisy neighbor) — five
# explanations for one symptom, which was itself the signal: a long job
# driven from a sub-agent's own foreground loop does not survive whatever
# ends that sub-agent's turn, regardless of which resource happened to be
# short at the time. The fix is not preventing the death (it cannot be, from
# here) but making it cost one cell instead of the whole grid: this script
# now resumes from `benchmarks/lib/sweep_progress.py`'s PROGRESS.json (which
# W values already completed), runs exactly the next PENDING cell, records
# its result — including machine-load/disk-space snapshots at cell start
# AND end (`benchmarks/lib/machine_load_snapshot.py`,
# `benchmarks/lib/disk_space_snapshot.py`) — and returns control. A kill or
# crash mid-cell leaves that cell's PROGRESS.json entry absent, so the next
# invocation retries exactly that cell, never the ones already recorded.
#
# Still true, unchanged: one reproduce.sh invocation per cell, against its
# own ephemeral container. No parallelism: a fan-out on this machine on
# 2026-08-08 drove load to 37 and swapped 11.9 GB.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT" || exit 1

# source: docs/provenance/trust-factor-calibration.md §Grid — brackets the
# 0.8 -> 0.7 transition found by the adversarial pre-sweep. 1.0 is the control.
GRID=(1.0 0.8 0.7 0.6 0.5)

# Empty-array expansion under `set -u` is an "unbound variable" error on the
# bash 3.2 that ships with macOS, so the flag is carried as a plain string and
# left unquoted at the call site (word-split on purpose: zero args when empty).
QUICK_FLAG=""
[[ "${1:-}" == "--quick" ]] && QUICK_FLAG="--quick"

# Fixed location, not a fresh timestamp per invocation: resume needs the
# NEXT call to find the SAME PROGRESS.json the previous one wrote.
OUT_ROOT="benchmarks/results/trust-factor-sweep/active"
mkdir -p "$OUT_ROOT"
LOG="${OUT_ROOT}/sweep.log"

snapshot_json() {
    uv run python -c "
import json, sys
sys.path.insert(0, 'benchmarks/lib')
from machine_load_snapshot import machine_load_snapshot
from disk_space_snapshot import disk_space_snapshot
print(json.dumps({'machine_load': machine_load_snapshot(), 'disk_space': disk_space_snapshot()}))
"
}

next_pending_w() {
    uv run python -c "
import sys
sys.path.insert(0, 'benchmarks/lib')
from sweep_progress import next_pending_w
w = next_pending_w([1.0, 0.8, 0.7, 0.6, 0.5], '${OUT_ROOT}')
print('' if w is None else w)
"
}

W="$(next_pending_w)"
if [[ -z "$W" ]]; then
    echo "GRID COMPLETE — every cell in ${GRID[*]} has a status:complete entry in ${OUT_ROOT}/PROGRESS.json." | tee -a "$LOG"
    echo "NEXT: apply the decision rule and record the chosen W in docs/provenance/trust-factor-calibration.md." | tee -a "$LOG"
    exit 0
fi

CELL_DIR="${OUT_ROOT}/cell_W${W}"
mkdir -p "$CELL_DIR"
echo "" | tee -a "$LOG"
echo "=== cell W=${W} — started $(date -u +%H:%M:%SZ) ===" | tee -a "$LOG"

START_SNAPSHOT="$(snapshot_json)"

# Exported, not inlined: reproduce.sh spawns the benchmark processes, and
# retrieval_dispatch.py reads the value at import in each of them.
CORTEX_UNTRUSTED_ORIGIN_FACTOR="$W" \
    benchmarks/reproduce.sh \
    --only longmemeval,locomo,beam \
    --no-ablation \
    $QUICK_FLAG \
    >"${CELL_DIR}/reproduce.log" 2>&1
rc=$?

END_SNAPSHOT="$(snapshot_json)"

if [[ $rc -eq 0 ]]; then
    echo "cell W=${W}: OK" | tee -a "$LOG"
    STATUS="complete"
else
    echo "cell W=${W}: FAILED rc=${rc} (see ${CELL_DIR}/reproduce.log)" | tee -a "$LOG"
    STATUS="failed"
fi

# reproduce.sh writes into benchmarks/results/repro/<its own stamp>/;
# record which one belongs to this cell so the summary can be rebuilt
# without guessing from timestamps.
latest_repro="$(ls -td benchmarks/results/repro/*/ 2>/dev/null | head -1)"
echo "${latest_repro}" > "${CELL_DIR}/repro_dir.txt"
echo "cell W=${W} results: ${latest_repro}" | tee -a "$LOG"

uv run python -c "
import json, sys
sys.path.insert(0, 'benchmarks/lib')
from sweep_progress import record_cell_result

start = json.loads('''${START_SNAPSHOT}''')
end = json.loads('''${END_SNAPSHOT}''')
record_cell_result(
    '${OUT_ROOT}',
    ${W},
    status='${STATUS}',
    repro_dir='${latest_repro}' or None,
    snapshots={
        'machine_load_at_start': start['machine_load'],
        'disk_space_at_start': start['disk_space'],
        'machine_load_at_end': end['machine_load'],
        'disk_space_at_end': end['disk_space'],
    },
)
"

echo "" | tee -a "$LOG"
echo "cell W=${W} recorded to ${OUT_ROOT}/PROGRESS.json — control returned." | tee -a "$LOG"
remaining="$(next_pending_w)"
if [[ -n "$remaining" ]]; then
    echo "NEXT PENDING CELL: W=${remaining}. Re-run this script to continue." | tee -a "$LOG"
else
    echo "GRID COMPLETE — every cell has reported." | tee -a "$LOG"
fi
