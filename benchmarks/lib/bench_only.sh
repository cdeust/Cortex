#!/usr/bin/env bash
# source: ADR-0859
# Sourced by benchmarks/reproduce.sh. Pure functions, no side effects.

# Canonical selection tokens want_bench() matches, plus the aliases the
# script itself prints as artifact names (ablation_bench_id).
# source: ADR-0859
BENCH_ONLY_CANONICAL="longmemeval locomo beam decision-ids"

bench_only_canonical_token() {
    case "$1" in
        longmemeval|longmemeval-s) echo "longmemeval" ;;
        beam|beam-100K)            echo "beam" ;;
        locomo)                    echo "locomo" ;;
        decision-ids)              echo "decision-ids" ;;
        *)                         return 1 ;;
    esac
}

# Rewrites ONLY as canonical comma-separated tokens, or fails closed with
# the accepted list on stderr. An empty ONLY means every benchmark.
# source: ADR-0859
validate_only() {
    [ -z "${ONLY:-}" ] && return 0
    case ",$ONLY," in (*,,*)
        echo "error: --only contains an empty token in '$ONLY'" >&2
        echo "accepted: $BENCH_ONLY_CANONICAL (aliases: longmemeval-s, beam-100K)" >&2
        return 2 ;;
    esac
    local raw token canonical out=""
    IFS=',' read -r -a raw <<< "$ONLY"
    for token in "${raw[@]}"; do
        if [ -z "$token" ]; then
            echo "error: --only contains an empty token in '$ONLY'" >&2
            echo "accepted: $BENCH_ONLY_CANONICAL (aliases: longmemeval-s, beam-100K)" >&2
            return 2
        fi
        if ! canonical="$(bench_only_canonical_token "$token")"; then
            echo "error: --only '$token' selects no benchmark; nothing would run." >&2
            echo "accepted: $BENCH_ONLY_CANONICAL (aliases: longmemeval-s, beam-100K)" >&2
            return 2
        fi
        out="${out:+$out,}$canonical"
    done
    ONLY="$out"
}
