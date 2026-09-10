#!/usr/bin/env bash
# source: ADR-0859
#
#
# source: ADR-0859
#
#
# source: ADR-0859
#
#
#
#
#
#
#
#
#
#
#
# source: ADR-0859
#
#
#
# source: ADR-0859
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#
# source: ADR-0859
#
#
#
#
#
#
# source: ADR-0859
#
#
#
#
#
#
#
#
#
#
#
#
#
#
#

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# source: ADR-0859
#
#
#
#
#
#
#
V4_MECHANISMS=(
    ACTIVE_FORGETTING
    VALUE_PRIORITY
    HABITUATION
    CONFLICT_MONITOR
    DUAL_PROCESS
    SLEEP_PHASES
    TARGETED_REACTIVATION
    EXTINCTION
    STRESS_MODULATION
    GOAL_MAINTENANCE
    FORWARD_MODEL
    CONFABULATION_GATE
    ATTENTIONAL_CONTROL
)

# ── LongMemEval-S dataset (the one dataset we can pin by content hash).
DATASET_PATH="$REPO_ROOT/benchmarks/longmemeval/longmemeval_s.json"
# source: ADR-0859
DATASET_URL="https://huggingface.co/datasets/xiaowu0162/LongMemEval/resolve/main/longmemeval_s"
# source: ADR-0859
#
DATASET_SHA256="08d8dad4be43ee2049a22ff5674eb86725d0ce5ff434cde2627e5e8e7e117894"

# source: ADR-0859
#
#
#
#
#
#
# source: ADR-0859
#
#
#
#
#
#
#
#
#
#
#
#
FLOOR_LME_R10=0.982
FLOOR_LME_MRR=0.914
FLOOR_LOCOMO_R10=0.915
FLOOR_LOCOMO_MRR=0.805
FLOOR_TOLERANCE=0.005

# ── Ephemeral PostgreSQL + pgvector (any PG>=15 with vector works; the schema
# code creates the extension itself on first connect).
#
# Finalize CONTAINER, PG_PORT, and BENCH_DB_URL inside start_db(); read the URL only afterward.
# source: ADR-0859
PG_IMAGE="pgvector/pgvector:pg16"
CONTAINER="cortex-bench-pg-$$-$(od -An -N4 -tx1 /dev/urandom | tr -d ' \n')"
PG_PORT=""
BENCH_DB_URL=""

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RESULTS_DIR="$REPO_ROOT/benchmarks/results/repro/$STAMP"
LOCK_DIR="$REPO_ROOT/benchmarks/.reproduce.lock"

# ── Parsed options (defaults) ────────────────────────────────────────────────
ONLY=""                 # empty => all benchmarks
RUN_ABLATION=1
RUN_BENCHMARKS=1
ABLATE_ON="locomo"
QUICK=0
LIMIT=""
KEEP_DB=0
RERANKER_CELL=""        # explicit W4-2 experiment; production defaults unchanged
NO_REGRESSION=0
PASSTHROUGH=()
started_container=0

# shellcheck source=benchmarks/lib/bench_regression.sh
. "$REPO_ROOT/benchmarks/lib/bench_regression.sh"
# shellcheck source=benchmarks/lib/bench_only.sh
. "$REPO_ROOT/benchmarks/lib/bench_only.sh"

# ── Helpers ──────────────────────────────────────────────────────────────────
need_cmd() {
    command -v "$1" >/dev/null 2>&1 || { echo "error: '$1' is required but not installed." >&2; exit 1; }
}

sha256_of() {
    if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | awk '{print $1}'
    else shasum -a 256 "$1" | awk '{print $1}'; fi
}

parse_args() {
    while [ $# -gt 0 ]; do
        case "$1" in
            --only)          ONLY="$2"; shift 2 ;;
            --only=*)        ONLY="${1#*=}"; shift ;;
            --no-ablation)   RUN_ABLATION=0; shift ;;
            --ablation-only) RUN_BENCHMARKS=0; shift ;;
            --ablate-on)     ABLATE_ON="$2"; shift 2 ;;
            --ablate-on=*)   ABLATE_ON="${1#*=}"; shift ;;
            --quick)         QUICK=1; shift ;;
            --limit)         LIMIT="$2"; shift 2 ;;
            --limit=*)       LIMIT="${1#*=}"; shift ;;
            --keep-db)       KEEP_DB=1; shift ;;
            --reranker-cell) RERANKER_CELL="$2"; shift 2 ;;
            --results-dir)   RESULTS_DIR="$2"; shift 2 ;;
            --no-regression) NO_REGRESSION=1; shift ;;
            --baseline-ref)  BASELINE_REF="$2"; shift 2 ;;
            --baseline-ref=*) BASELINE_REF="${1#*=}"; shift ;;
            *)               PASSTHROUGH+=("$1"); shift ;;
        esac
    done
    validate_only || exit 2
    check_reranker_cell
}

check_reranker_cell() {
    # Cell preflight precedes Docker/model loading. Its cache must already
    # contain the separately fetched, SHA-verified pinned archive and files.
    if [ -n "$RERANKER_CELL" ]; then
        if [ "$RUN_ABLATION" != "0" ]; then
            echo "error: --reranker-cell requires --no-ablation" >&2
            exit 1
        fi
        (cd "$REPO_ROOT" && uv run --extra benchmarks python -m \
            benchmarks.reranker_matrix.cache check "$RERANKER_CELL")
    fi
}

want_bench() {
    # source: ADR-0859
    [ -z "$ONLY" ] && return 0
    case ",$ONLY," in (*",$1,"*) return 0 ;; esac
    return 1
}

fetch_longmemeval() {
    if [ -f "$DATASET_PATH" ]; then
        echo "==> LongMemEval dataset present."
    else
        echo "==> Downloading LongMemEval-S (~265 MB) from the official HF repo..."
        curl -L --fail --progress-bar -o "$DATASET_PATH" "$DATASET_URL"
    fi
    local actual; actual="$(sha256_of "$DATASET_PATH")"
    if [ "$actual" != "$DATASET_SHA256" ]; then
        echo "error: LongMemEval dataset checksum mismatch." >&2
        echo "  expected: $DATASET_SHA256" >&2
        echo "  actual:   $actual" >&2
        echo "Delete $DATASET_PATH and retry." >&2
        exit 1
    fi
    echo "==> LongMemEval checksum OK."
}

# source: ADR-0859
#
#
#
# shellcheck source=benchmarks/lib/bench_container.sh
. "$REPO_ROOT/benchmarks/lib/bench_container.sh"

# source: ADR-0859
#
#
#
#
#
#
#
#
#
#
#
acquire_lock() {
    if mkdir "$LOCK_DIR" 2>/dev/null; then
        echo $$ > "$LOCK_DIR/pid"
        return
    fi
    local holder; holder="$(cat "$LOCK_DIR/pid" 2>/dev/null || echo '?')"
    if [ "$holder" != "?" ] && kill -0 "$holder" 2>/dev/null; then
        echo "error: another reproduce.sh run (pid $holder) is already active." >&2
        echo "Concurrent runs share one database and corrupt each other's results." >&2
        echo "Wait for it to finish (or stop it), then retry." >&2
        exit 1
    fi
    echo "==> Removing stale lock (pid $holder is not running)."
    rm -rf "$LOCK_DIR" && mkdir "$LOCK_DIR" && echo $$ > "$LOCK_DIR/pid"
}

teardown() {
    remove_container
    rm -rf "$LOCK_DIR"
}

# source: ADR-0859
run_bench() {
    local name="$1"; shift          # longmemeval-s | locomo | beam-100K
    local script="$1"; shift        # path to run_benchmark.py
    local out="$RESULTS_DIR/${name}.json"
    local entry=("$script")
    if [ -n "$RERANKER_CELL" ]; then
        entry=(-m benchmarks.reranker_matrix.entry "$RERANKER_CELL" "$script")
    fi
    echo
    echo "════════════════════════════════════════════════════════════════════"
    echo "  BENCHMARK: $name"
    echo "════════════════════════════════════════════════════════════════════"
    # source: ADR-0859
    #
    #
    DATABASE_URL="$BENCH_DB_URL" uv run --extra benchmarks python \
        "${entry[@]}" --results-out "$out" "$@" \
        ${PASSTHROUGH[@]+"${PASSTHROUGH[@]}"}
}

# source: ADR-0859
#
#
ablation_bench_id() {
    case "$1" in
        longmemeval|longmemeval-s) echo "longmemeval-s" ;;
        beam|beam-100K)            echo "beam-100K" ;;
        locomo)                    echo "locomo" ;;
        *)                         echo "$1" ;;
    esac
}

run_ablation_sweep() {
    local bench_id; bench_id="$(ablation_bench_id "$ABLATE_ON")"
    echo
    echo "════════════════════════════════════════════════════════════════════"
    echo "  ABLATION SWEEP on '$bench_id' (baseline + ${#V4_MECHANISMS[@]} mechanisms)"
    echo "════════════════════════════════════════════════════════════════════"
    local mech_args=()
    local m
    for m in "${V4_MECHANISMS[@]}"; do mech_args+=(--mechanism "$m"); done
    local quick_arg=()
    [ "$QUICK" = "1" ] && quick_arg+=(--quick)
    # source: ADR-0859
    #
    DATABASE_URL="$BENCH_DB_URL" uv run --extra benchmarks python \
        "$REPO_ROOT/benchmarks/lib/ablation_runner.py" \
        --benchmark "$bench_id" "${mech_args[@]}" \
        ${quick_arg[@]+"${quick_arg[@]}"}
}

write_manifest() {
    local entry=("$REPO_ROOT/benchmarks/lib/write_manifest.py")
    if [ -n "$RERANKER_CELL" ]; then
        entry=(-m benchmarks.reranker_matrix.entry "$RERANKER_CELL" "${entry[0]}")
    fi
    local git_sha; git_sha="$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"
    DATABASE_URL="$BENCH_DB_URL" uv run --extra benchmarks python \
        "${entry[@]}" \
        "$RESULTS_DIR" "$git_sha" "$DATASET_SHA256" "$PG_IMAGE" "$CONTAINER" "$PG_PORT" "$$"
}

print_summary() {
    local abl_id; abl_id="$(ablation_bench_id "$ABLATE_ON")"
    uv run --extra benchmarks python - "$RESULTS_DIR" "$REPO_ROOT/benchmarks/results/ablation/$abl_id" <<'PY'
import json, sys
from pathlib import Path
repro_dir, abl_dir = Path(sys.argv[1]), Path(sys.argv[2])
def load(p):
    try: return json.loads(Path(p).read_text())
    except Exception: return {}
print("\n" + "=" * 68)
print("  CONSOLIDATED RESULTS  ({})".format(repro_dir.name))
print("=" * 68)
print(f"{'benchmark':<20}{'MRR':>12}{'Recall@10':>14}{'n':>8}")
print("-" * 68)
for f in sorted(repro_dir.glob("*.json")):
    if f.name == "MANIFEST.json": continue
    d = load(f)
    mrr = d.get("overall_mrr")
    # Read the runner-specific metric and question-count keys; accept numeric zero.
    # source: ADR-0859
    r10 = d.get("overall_recall10")
    if r10 is None:
        r10 = d.get("overall_r10")
    n = ""
    for key in ("n_questions", "n_conversations", "total_questions", "n"):
        if d.get(key) is not None:
            n = d[key]
            break
    smrr = f"{mrr:.4f}" if isinstance(mrr, (int, float)) else "—"
    sr10 = f"{r10:.4f}" if isinstance(r10, (int, float)) else "—"
    print(f"{f.stem:<20}{smrr:>12}{sr10:>14}{str(n):>8}")
# Ablation deltas vs baseline, if present.
base = load(abl_dir / "BASELINE.json")
b_mrr = base.get("mrr") or base.get("overall_mrr")
if isinstance(b_mrr, (int, float)):
    print("\n" + "-" * 68)
    print(f"  ABLATION vs baseline MRR={b_mrr:.4f} on {abl_dir.name}")
    print(f"{'mechanism ablated':<28}{'MRR':>10}{'ΔMRR':>12}")
    print("-" * 68)
    for f in sorted(abl_dir.glob("*.json")):
        if f.stem == "BASELINE": continue
        d = load(f)
        m = d.get("mrr") or d.get("overall_mrr")
        if not isinstance(m, (int, float)): continue
        print(f"{f.stem:<28}{m:>10.4f}{m - b_mrr:>+12.4f}")
print("=" * 68)
PY
}

# source: ADR-0859
#
#
#
#
#
#
# source: ADR-0859
#
#
#
#
#
#
#
#
#
#
#
#
#
#
check_floors() {
    uv run --extra benchmarks python - "$RESULTS_DIR" \
        "$FLOOR_LME_R10" "$FLOOR_LME_MRR" "$FLOOR_LOCOMO_R10" "$FLOOR_LOCOMO_MRR" \
        "$FLOOR_TOLERANCE" <<'PY'
import json, sys
from pathlib import Path
rd = Path(sys.argv[1])
lme_r10, lme_mrr, loc_r10, loc_mrr, tol = map(float, sys.argv[2:7])
floors = {
    "longmemeval-s": {"overall_recall10": lme_r10, "overall_mrr": lme_mrr},
    "locomo": {"overall_recall10": loc_r10, "overall_mrr": loc_mrr},
}
failed = False
for stem, expected in floors.items():
    p = rd / f"{stem}.json"
    if not p.exists():
        continue  # source: ADR-0859
    d = json.loads(p.read_text())
    for key, floor in expected.items():
        got = d.get(key)
        if not isinstance(got, (int, float)):
            print(f"FLOOR CHECK {stem}.{key}: metric missing — FAIL")
            failed = True
            continue
        got = round(got, 4)
        delta = got - floor
        status = "PASS" if delta >= -tol else "FAIL"
        if status == "FAIL":
            failed = True
        print(f"FLOOR CHECK {stem}.{key}: {got:.4f} vs floor {floor:.4f} ({delta:+.4f}) {status}")
if failed:
    print("\nFLOOR CHECK: full-run scores deviate from the published numbers (non-blocking).")
    print("This does not fail the build — see the FLOOR_* comment above for why, and use")
    print("--no-regression to gate a PR against its own baseline instead.")
PY
}

main() {
    parse_args "$@"
    need_cmd docker; need_cmd curl; need_cmd uv
    if ! docker info >/dev/null 2>&1; then
        echo "error: the Docker daemon is not running (start Docker Desktop / colima)." >&2
        exit 1
    fi
    mkdir -p "$RESULTS_DIR"

    # source: ADR-0859
    #
    #
    #
    #
    #
    #
    #
    uv run python "$REPO_ROOT/benchmarks/lib/write_manifest.py" \
        --snapshot "$RESULTS_DIR"

    # source: ADR-0859
    if [ "$RUN_BENCHMARKS" = "1" ] && want_bench longmemeval; then fetch_longmemeval; fi
    if [ "$RUN_ABLATION" = "1" ] && [ "$ABLATE_ON" = "longmemeval-s" ]; then fetch_longmemeval; fi

    if [ "$NO_REGRESSION" = "1" ]; then preflight_regression_datasets; fi

    acquire_lock
    trap teardown EXIT
    start_db
    cd "$REPO_ROOT"

    # source: ADR-0859
    lm_args=(); lo_args=(); be_args=(--split 100K)
    if [ -n "$LIMIT" ]; then lm_args+=(--limit "$LIMIT"); lo_args+=(--limit "$LIMIT"); be_args+=(--limit "$LIMIT")
    elif [ "$QUICK" = "1" ]; then lm_args+=(--limit 10); lo_args+=(--limit 1); be_args+=(--limit 2); fi

    if [ "$RUN_BENCHMARKS" = "1" ]; then
        want_bench longmemeval && run_bench "longmemeval-s" \
            "benchmarks/longmemeval/run_benchmark.py" \
            ${lm_args[@]+"${lm_args[@]}"}
        want_bench locomo && run_bench "locomo" \
            "benchmarks/locomo/run_benchmark.py" \
            ${lo_args[@]+"${lo_args[@]}"}
        want_bench beam && run_bench "beam-100K" \
            "benchmarks/beam/run_benchmark.py" "${be_args[@]}"
        if want_bench decision-ids; then
            uv run --extra benchmarks python -m benchmarks.decision_ids.run_bench \
                --output "$RESULTS_DIR/decision-ids.json"
        fi
    fi

    if [ "$RUN_ABLATION" = "1" ]; then
        run_ablation_sweep
    fi

    write_manifest
    print_summary
    # Compare published question counts only for full runs.
    # source: ADR-0859
    if [ "$RUN_BENCHMARKS" = "1" ] && [ -z "$LIMIT" ] && [ "$QUICK" = "0" ]; then
        check_floors
    fi

    # source: ADR-0859
    #
    #
    #
    #
    if [ "$NO_REGRESSION" = "1" ]; then
        if [ "$RUN_BENCHMARKS" != "1" ] || [ -n "$LIMIT" ] || [ "$QUICK" = "1" ]; then
            echo "error: --no-regression requires a full benchmark run (no --ablation-only, --quick or --limit)." >&2
            exit 1
        fi
        run_baseline_benchmarks
        check_regression
    fi

    echo
    echo "==> All artifacts under: $RESULTS_DIR"
    if [ "$RUN_ABLATION" = "1" ]; then
        echo "==> Ablation artifacts under: benchmarks/results/ablation/$(ablation_bench_id "$ABLATE_ON")/"
    fi
}

main "$@"
