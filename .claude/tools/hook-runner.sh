#!/usr/bin/env bash
# hook-runner.sh — Dispatch hook events to the right hook script
#
# Usage:
#   tools/hook-runner.sh <event> [context...]
#
# Events: pre-commit, post-commit, pre-push, session-start, session-end
# Exit codes: passes through from the hook script

set -euo pipefail
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOOKS_DIR="$REPO_ROOT/hooks"
EVENT="${1:-}"
shift || true

case "$EVENT" in
  pre-commit)   exec "$HOOKS_DIR/pre-commit-zetetic.sh" "$@" ;;
  post-commit)  exec "$HOOKS_DIR/post-commit-difficulty.sh" "$@" ;;
  pre-push)     exec "$HOOKS_DIR/pre-push-review.sh" "$@" ;;
  session-start) exec "$HOOKS_DIR/session-start.sh" "$@" ;;
  session-end)  exec "$HOOKS_DIR/session-end.sh" "$@" ;;
  *) echo "Unknown event: $EVENT. Available: pre-commit, post-commit, pre-push, session-start, session-end" >&2; exit 2 ;;
esac
