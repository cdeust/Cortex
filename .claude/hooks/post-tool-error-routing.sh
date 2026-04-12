#!/usr/bin/env bash
# post-tool-error-routing.sh — Suggest diagnostic genius agent when a tool call fails
# Runs after tool errors; must complete in <500ms.
# Input: $1 = tool name, $2 = error message (or excerpt)
set -euo pipefail

TOOL="${1:-}"
ERROR="${2:-}"
ERROR_LOWER="$(echo "$ERROR" | tr '[:upper:]' '[:lower:]')"

suggest() {
  echo "Suggested genius agent: $1"
  echo "Reason: $2"
  echo "Invoke with: /genius-invoke $1 \"$ERROR\""
}

# Build / compilation errors
if echo "$ERROR_LOWER" | grep -qE 'compile|build|syntax|parse|undefined|import|module not found|cannot find'; then
  suggest "dijkstra" "Build/compile error — structured correctness analysis"
  exit 0
fi

# Test failures
if echo "$ERROR_LOWER" | grep -qE 'test.*fail|assert|expect.*to|mismatch|not equal|test.*error'; then
  suggest "fisher" "Test failure — experimental design and statistical reasoning"
  exit 0
fi

# Timeout / performance
if echo "$ERROR_LOWER" | grep -qE 'timeout|timed.out|deadline|too slow|exceeded.*time|oom|out of memory'; then
  suggest "erlang" "Timeout/capacity issue — queuing theory and capacity planning"
  exit 0
fi

# Permission / access errors
if echo "$ERROR_LOWER" | grep -qE 'permission|denied|forbidden|eacces|not permitted|chmod'; then
  suggest "hamilton" "Permission error — defensive design and failure handling"
  exit 0
fi

# Auth / credential errors
if echo "$ERROR_LOWER" | grep -qE 'auth|unauthorized|401|403|token|credential|login|certificate'; then
  suggest "rejewski" "Auth/credential error — reverse engineering and decipherment"
  exit 0
fi

# Type / contract errors
if echo "$ERROR_LOWER" | grep -qE 'type.*error|cannot assign|incompatible|contract|interface|trait'; then
  suggest "liskov" "Type/contract error — substitutability and composability analysis"
  exit 0
fi

# No match — no suggestion
exit 0
