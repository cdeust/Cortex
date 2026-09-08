#!/usr/bin/env bash
# No-regression gate: compares the checked-out tree's benchmark scores
# against the SAME benchmarks run on a baseline ref (default origin/main),
# in the SAME ephemeral container/DB, instead of gating on the fixed
# FLOOR_* constants in reproduce.sh.
#
# Why this exists (source: cdeust/Cortex PR #492, 2026-09-07): the
# published floors (README benchmark tables, E1 v3 campaign) no longer
# match what main itself measures — LongMemEval MRR 0.904988 vs floor
# 0.914, LoCoMo MRR 3-run mean 0.779868 vs floor 0.805, LoCoMo Recall@10
# 0.889506 vs floor 0.915 — all measured on main@6ec76a0e via this same
# reproduce.sh. That gap predates and is independent of any pending PR:
# every PR built on top of that commit inherits an already-failing floor
# gate it did not cause and cannot pass by itself. Lowering FLOOR_* to
# match would hide the drift (same anti-pattern rejected for the pyright
# ratchet in issue #188: "raising the floor would just hide the debt").
# The fix is the same shape as that issue's resolution and as
# scripts/check_craftsmanship.py's own baseline discipline (diff against
# the base ref, never the working tree, never a hand-edited threshold):
# gate on whether THIS tree is worse than its own baseline, not on
# whether it clears a number nothing currently clears.
#
# Contract with the caller (reproduce.sh):
#   REPO_ROOT, RESULTS_DIR, BENCH_DB_URL, PASSTHROUGH[]   (read)
#   ONLY, QUICK, LIMIT                                    (read, scope which
#                                                           benchmarks/limits
#                                                           the baseline run
#                                                           mirrors)
#   want_bench(), run_bench()                             (read, reused so
#                                                           the baseline run
#                                                           takes the exact
#                                                           same code path)
#   REGRESSION_TOLERANCE                                  (read; reproduce.sh
#                                                           default below)
#
# source: tolerance reuses FLOOR_TOLERANCE's own provenance (0.5 percentage
# points, benchmarks/results/a3_longmemeval_post_refactor.md design §8) —
# a regression gate has no reason to be stricter than the floor gate it
# replaces as the blocking check.
REGRESSION_TOLERANCE="${REGRESSION_TOLERANCE:-0.005}"
BASELINE_REF="${BASELINE_REF:-origin/main}"
BASELINE_RESULTS_DIR=""

# Run the same benchmark set (respecting --only/--quick/--limit) against
# BASELINE_REF's code, in an isolated git worktree, writing results under
# $RESULTS_DIR/baseline/. Reuses the already-running container: harnesses
# self-clean (purge is_benchmark rows on open, per reproduce.sh's header),
# so a second harness run against the same DB is safe and does not require
# a second container.
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

    # Inside the repo, under the directory Claude Code's own worktree tooling
    # uses (gitignored via .claude/*) — never /tmp or a sibling directory, where
    # a killed run leaves a worktree nothing reclaims (owner correction 2026-09-08).
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

    # cd into the worktree so `uv run` resolves ITS pyproject.toml/uv.lock —
    # the baseline may pin different dependency versions than HEAD, and
    # running it under HEAD's resolved env would not actually measure the
    # baseline's code.
    (
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

# Compare $RESULTS_DIR/<stem>.json (HEAD, already produced by run_bench)
# against $RESULTS_DIR/baseline/<stem>.json (just produced above). Fails
# only when HEAD is more than REGRESSION_TOLERANCE below its own baseline —
# never against a fixed published number. BEAM is intentionally excluded,
# matching FLOOR check_floors' own scope note (its numbers predate the
# 200->395-question split rebasing and are within-system comparison only,
# which is exactly what this gate does — but BEAM still has no committed
# per-question stability data to size a tolerance from).
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
        # Round to the same 4-decimal precision reproduce.sh prints, so the
        # pass/fail line matches exactly what a reader sees in this log —
        # comparing at higher hidden precision than what's displayed is the
        # rounding mismatch that made single-run borderline cases confusing
        # to bisect (reproduce.sh's own check_floors docstring, LoCoMo
        # same-commit noise note, stdev 0.0022 measured 2026-07-14).
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
