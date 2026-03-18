#!/bin/bash
# Quick benchmark suite — scoped for fast iteration
# Runs ~2-3 minutes total instead of ~30 minutes for full suite
#
# Usage: bash benchmarks/quick_test.sh

set -e
echo "=== JARVIS Quick Benchmark Suite ==="
echo ""

echo "--- LongMemEval (50 of 500 Qs) ---"
python3 benchmarks/longmemeval/run_benchmark.py --variant s --limit 50 2>&1 | grep -E '(MRR|R@10|Total)'

echo ""
echo "--- LoCoMo (2 of 10 conversations) ---"
python3 benchmarks/locomo/run_benchmark.py --limit 2 2>&1 | grep -E '(OVERALL|Total|Category)'

echo ""
echo "--- BEAM (5 of 20 conversations) ---"
python3 benchmarks/beam/run_benchmark.py --split 100K --limit 5 2>&1 | grep -E '(OVERALL|Total|Ability)'

echo ""
echo "--- EverMemBench (topic 01, 200 msgs) ---"
python3 benchmarks/evermembench/run_benchmark.py --topic 01 --limit 200 2>&1 | grep -E '(OVERALL|By dimension|Total)'

echo ""
echo "=== Done ==="
