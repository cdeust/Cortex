#!/usr/bin/env bash
# balance-auditor.sh — Quick conservation check for data pipelines
#
# Usage:
#   tools/balance-auditor.sh <input-count> <output-count> [filtered-count] [error-count]
#
# Verifies: input = output + filtered + errors. Reports residual.
# Exit codes: 0 balanced, 1 imbalanced

set -euo pipefail

INPUT="${1:-0}"; OUTPUT="${2:-0}"; FILTERED="${3:-0}"; ERRORS="${4:-0}"

[[ "$INPUT" -eq 0 ]] && { echo "usage: $0 <input> <output> [filtered] [errors]" >&2; exit 1; }

ACCOUNTED=$((OUTPUT + FILTERED + ERRORS))
RESIDUAL=$((INPUT - ACCOUNTED))

echo "Balance Audit"
echo "  Input:    $INPUT"
echo "  Output:   $OUTPUT"
echo "  Filtered: $FILTERED"
echo "  Errors:   $ERRORS"
echo "  ─────────────"
echo "  Accounted: $ACCOUNTED"
echo "  Residual:  $RESIDUAL"

if [[ "$RESIDUAL" -ne 0 ]]; then
  echo ""
  echo "IMBALANCED: $RESIDUAL records unaccounted for."
  echo "The residual is real — find its carrier (Curie method)."
  exit 1
else
  echo ""
  echo "BALANCED: all records accounted for."
  exit 0
fi
