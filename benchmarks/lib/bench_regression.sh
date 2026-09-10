#!/usr/bin/env bash
# source: ADR-0067
# source: ADR-0067
# source: ADR-0067
REGRESSION_TOLERANCE="${REGRESSION_TOLERANCE:-0.005}"
BASELINE_REF="${BASELINE_REF:-origin/main}"
BASELINE_RESULTS_DIR=""

# Reuse the HEAD datasets in the baseline worktree.
# source: ADR-0067
preflight_regression_datasets() {
    local name relative
    for name in longmemeval locomo; do
        if ! want_bench "$name"; then continue; fi
        case "$name" in
            longmemeval) relative="benchmarks/longmemeval/longmemeval_s.json" ;;
            locomo) relative="benchmarks/locomo/locomo10.json" ;;
        esac
        if [ ! -r "$REPO_ROOT/$relative" ]; then
            echo "error: regression dataset missing or unreadable: $REPO_ROOT/$relative" >&2
            return 1
        fi
    done
}

copy_regression_datasets() {
    local destination="$1" name relative
    preflight_regression_datasets || return 1
    for name in longmemeval locomo; do
        if ! want_bench "$name"; then continue; fi
        case "$name" in
            longmemeval) relative="benchmarks/longmemeval/longmemeval_s.json" ;;
            locomo) relative="benchmarks/locomo/locomo10.json" ;;
        esac
        cp "$REPO_ROOT/$relative" "$destination/$relative" || return 1
        cmp -s "$REPO_ROOT/$relative" "$destination/$relative" || return 1
    done
}

# Run the selected benchmarks in an isolated baseline worktree using the existing container.
# source: ADR-0067
run_baseline_benchmarks() {
    local baseline_sha
    baseline_sha="$(git -C "$REPO_ROOT" rev-parse "$BASELINE_REF" 2>/dev/null)" || {
        echo "error: could not resolve baseline ref '$BASELINE_REF' (fetch it first?)." >&2
        exit 1
    }
    local head_sha; head_sha="$(git -C "$REPO_ROOT" rev-parse HEAD)"
    if [ "$baseline_sha" = "$head_sha" ]; then
        echo "==> Baseline ref '$BASELINE_REF' is HEAD itself — nothing to compare against." >&2
        echo "    (running from a checkout of the baseline ref, or the ref is stale)." >&2
        exit 1
    fi

    BASELINE_RESULTS_DIR="$RESULTS_DIR/baseline"
    mkdir -p "$BASELINE_RESULTS_DIR"

    # source: ADR-0067
    mkdir -p "$REPO_ROOT/.claude/worktrees"
    local wt_dir; wt_dir="$(mktemp -d "$REPO_ROOT/.claude/worktrees/bench-baseline-XXXXXX")"
    echo
    echo "════════════════════════════════════════════════════════════════════"
    echo "  NO-REGRESSION BASELINE: $BASELINE_REF (${baseline_sha:0:12}) in $wt_dir"
    echo "════════════════════════════════════════════════════════════════════"
    git -C "$REPO_ROOT" worktree add --detach "$wt_dir" "$baseline_sha" >/dev/null

    local lm_args=(); local lo_args=()
    if [ -n "$LIMIT" ]; then lm_args+=(--limit "$LIMIT"); lo_args+=(--limit "$LIMIT")
    elif [ "$QUICK" = "1" ]; then lm_args+=(--limit 10); lo_args+=(--limit 1); fi

    # Run uv inside the baseline worktree.
    # source: ADR-0067
    (
        # Preserve errexit and clean up on subshell exit.
        # source: ADR-0067
        trap 'git -C "$REPO_ROOT" worktree remove --force "$wt_dir" >/dev/null 2>&1 || true' EXIT
        copy_regression_datasets "$wt_dir"
        cd "$wt_dir"
        if want_bench longmemeval; then
            echo "==> [baseline] longmemeval-s"
            DATABASE_URL="$BENCH_DB_URL" uv run --extra benchmarks python \
                "$wt_dir/benchmarks/longmemeval/run_benchmark.py" \
                --results-out "$BASELINE_RESULTS_DIR/longmemeval-s.json" \
                ${lm_args[@]+"${lm_args[@]}"} \
                ${PASSTHROUGH[@]+"${PASSTHROUGH[@]}"}
        fi
        if want_bench locomo; then
            echo "==> [baseline] locomo"
            DATABASE_URL="$BENCH_DB_URL" uv run --extra benchmarks python \
                "$wt_dir/benchmarks/locomo/run_benchmark.py" \
                --results-out "$BASELINE_RESULTS_DIR/locomo.json" \
                ${lo_args[@]+"${lo_args[@]}"} \
                ${PASSTHROUGH[@]+"${PASSTHROUGH[@]}"}
        fi
    )
    local status=$?

    git -C "$REPO_ROOT" worktree remove --force "$wt_dir" >/dev/null 2>&1 || true
    if [ "$status" -ne 0 ]; then
        echo "error: baseline benchmark run failed (exit $status)." >&2
        exit "$status"
    fi
}

# source: ADR-0067
check_regression() {
    uv run --extra benchmarks python - "$RESULTS_DIR" "$BASELINE_RESULTS_DIR" \
        "$REGRESSION_TOLERANCE" <<'PY'
import json, sys
from pathlib import Path
rd, bd = Path(sys.argv[1]), Path(sys.argv[2])
tol = float(sys.argv[3])
stems = {"longmemeval-s": ["overall_recall10", "overall_mrr"],
         "locomo": ["overall_recall10", "overall_mrr"]}
failed = False
for stem, keys in stems.items():
    head_p, base_p = rd / f"{stem}.json", bd / f"{stem}.json"
    if not head_p.exists() or not base_p.exists():
        continue  # benchmark scoped out via --only
    head, base = json.loads(head_p.read_text()), json.loads(base_p.read_text())
    for key in keys:
        got, ref = head.get(key), base.get(key)
        if not isinstance(got, (int, float)) or not isinstance(ref, (int, float)):
            print(f"REGRESSION CHECK {stem}.{key}: metric missing — FAIL")
            failed = True
            continue
        # Round displayed and compared metrics to four decimal places.
        # source: ADR-0067
        got_r, ref_r = round(got, 4), round(ref, 4)
        delta = got_r - ref_r
        status = "PASS" if delta >= -tol else "FAIL"
        if status == "FAIL":
            failed = True
        print(f"REGRESSION CHECK {stem}.{key}: {got_r:.4f} vs baseline {ref_r:.4f} ({delta:+.4f}) {status}")
if failed:
    print("\nREGRESSION CHECK FAILED: HEAD scores below its own baseline by more than the tolerance.")
    print("This means the code under test is worse than the ref it was compared against — do not ship.")
    sys.exit(1)
print("\nREGRESSION CHECK PASSED: no score regressed vs baseline beyond tolerance.")
PY
}
