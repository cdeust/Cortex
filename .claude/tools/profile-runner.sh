#!/usr/bin/env bash
# profile-runner.sh — Wrapper for common profilers, auto-detecting language
#
# Usage:
#   tools/profile-runner.sh <command-to-profile>
#
# Auto-detects: Python (py-spy/cProfile), Node (--prof), Go (pprof), Rust (flamegraph)
# Exit codes: 0 success, 1 error, 2 no profiler available

set -euo pipefail
CMD="${1:-}"
[[ -z "$CMD" ]] && { echo "usage: $0 \"<command to profile>\"" >&2; exit 2; }

# Detect language from command
if echo "$CMD" | grep -qE '^python|\.py'; then
  if command -v py-spy &>/dev/null; then
    echo "Profiling with py-spy (sampling profiler)..."
    py-spy record --output profile.svg -- $CMD
    echo "Flamegraph: profile.svg"
  else
    echo "Profiling with cProfile..."
    python3 -m cProfile -s cumulative $CMD 2>&1 | head -30
  fi
elif echo "$CMD" | grep -qE '^node|\.js|\.ts'; then
  echo "Profiling with Node --prof..."
  node --prof $CMD
  echo "Run 'node --prof-process isolate-*.log' to analyze."
elif echo "$CMD" | grep -qE '^go |\.go'; then
  echo "Profiling with Go pprof..."
  go test -cpuprofile=cpu.prof -bench=. $CMD
  echo "Run 'go tool pprof cpu.prof' to analyze."
else
  echo "Language not auto-detected. Profile manually and use the Knuth agent to analyze the 3%."
  exit 2
fi
