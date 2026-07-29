#!/usr/bin/env bash
# Bare-container / DB-less MCP contract smoke test.
#
# Guards the regression fixed on fix/bare-container-contract (H4 root cause,
# see commit 5d71069c): third-party registry indexers (Glama et al.) run
# `docker build` from the bare repo, then `docker run --rm -i` with ZERO env
# vars and ZERO external services, and expect `tools/list` to answer with the
# standalone tool set. That contract silently broke for two months because
# nothing in CI exercised it — every CI job installs the `[postgresql]` extra
# and/or starts a database, so the "psycopg absent, no DB" path was never hit.
#
# This script builds the production image from the repo root Dockerfile, runs
# it with no environment variables and no linked services, sends `initialize`
# + `tools/list` over stdio (the real MCP transport — no HTTP port is
# exposed), and asserts the advertised tool count is at least the standalone
# baseline. `>=` (not `==`) so the gate does not need editing every time a
# new tool ships — it only fires when the count regresses.
#
# Usage:
#   scripts/docker_smoke.sh                  # build image + smoke test
#   scripts/docker_smoke.sh --skip-build      # reuse an already-built image
#   CORTEX_SMOKE_IMAGE=cortex:latest scripts/docker_smoke.sh --skip-build
#
# Exit code: 0 on success, non-zero (with a diagnostic on stderr) on failure.
# Used by both CI (.github/workflows/ci.yml, job `docker-smoke`) and local dev.

set -euo pipefail

# source: tests_py/test_main.py::TestMain::test_standalone_baseline_is_49_tools
# — the 49 standalone tools registered with zero upstream MCP servers
# reachable (codebase=False, prd=False), re-derived 2026-07-12 via a live
# `docker run` + `uv run hypermnesia-mcp` round-trip (fix/bare-container-
# contract root-cause report). `>=` guards against future regression without
# requiring an edit here every time a tool is added.
MIN_TOOL_COUNT="${CORTEX_SMOKE_MIN_TOOLS:-49}"
IMAGE="${CORTEX_SMOKE_IMAGE:-cortex-smoke:local}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SKIP_BUILD=0

for arg in "$@"; do
  case "$arg" in
    --skip-build) SKIP_BUILD=1 ;;
    *)
      echo "docker_smoke.sh: unknown argument '$arg'" >&2
      exit 2
      ;;
  esac
done

if [[ "$SKIP_BUILD" -eq 0 ]]; then
  echo "docker_smoke: building ${IMAGE} from ${REPO_ROOT}/Dockerfile ..." >&2
  docker build -t "$IMAGE" -f "${REPO_ROOT}/Dockerfile" "$REPO_ROOT"
fi

# Bare contract: no -e flags, no --link, no compose network. The container
# must self-select the SQLite fallback (CORTEX_RUNTIME=cowork, set in the
# Dockerfile itself) with zero external services.
# `notifications/initialized` carries NO "id". JSON-RPC 2.0 §4.1: "A
# Notification is a Request object without an 'id' member" — the presence of
# an id is the ONLY thing that distinguishes the two, so an id here made the
# server route the message to `ClientRequest`, whose method union does not
# contain any `notifications/*` member (verified against mcp.types:
# ClientRequest = ping|initialize|completion/complete|logging/setLevel|
# prompts/*|resources/*|tools/*|tasks/*; `notifications/initialized` lives
# only in ClientNotification). The server answered id=2 with -32602 and
# logged "28 validation errors for ClientRequest", one per union member.
#
# That is what made this gate FLAKY rather than simply broken: the malformed
# frame put the server on an error path mid-handshake, and whether it still
# answered id=3 before stdin EOF shut it down was a race. Same commit
# 18d4505 failed at 21:52Z and passed at 22:12Z. A correct handshake has no
# such error path.
REQUESTS=$'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"docker-smoke","version":"0"}}}\n{"jsonrpc":"2.0","method":"notifications/initialized"}\n{"jsonrpc":"2.0","id":3,"method":"tools/list","params":{}}\n'

echo "docker_smoke: running ${IMAGE} with zero env vars, sending initialize + tools/list over stdio ..." >&2

# Unique per run: two smoke runs on one runner must not read each other's
# diagnostics, and a stale file from a previous run must not be mistaken for
# this run's output.
#
# Explicit XXXXXX template, not `mktemp -t <prefix>`: GNU coreutils mktemp
# (the ubuntu-latest runner) requires the template to end in at least three
# X's and errors "too few X's in template" otherwise, while BSD/macOS mktemp
# treats -t's argument as a prefix and appends its own suffix. The bare -t
# form therefore passes locally on macOS and fails only on CI.
STDERR_LOG="$(mktemp "${TMPDIR:-/tmp}/docker_smoke_stderr.XXXXXX")"
PROTOCOL_ERRORS="$(mktemp "${TMPDIR:-/tmp}/docker_smoke_protocol_errors.XXXXXX")"
trap 'rm -f "$STDERR_LOG" "$PROTOCOL_ERRORS"' EXIT

# Portable timeout: GNU coreutils `timeout` ships on ubuntu-latest (GitHub
# Actions runner) but not on macOS by default (`gtimeout` from `brew install
# coreutils` is the local-dev equivalent). Fall back to no timeout wrapper
# rather than failing the script on a missing binary — docker itself is
# bounded below by `docker run --rm -i` returning once the container exits
# on stdin EOF, so an unbounded wait only risks hanging, not a false PASS.
TIMEOUT_CMD=""
if command -v timeout >/dev/null 2>&1; then
  TIMEOUT_CMD="timeout 60"
elif command -v gtimeout >/dev/null 2>&1; then
  TIMEOUT_CMD="gtimeout 60"
fi

RAW_OUTPUT="$(printf '%s' "$REQUESTS" | $TIMEOUT_CMD docker run --rm -i "$IMAGE" 2>"$STDERR_LOG" || true)"

if [[ -z "$RAW_OUTPUT" ]]; then
  echo "docker_smoke: FAIL — empty stdout from container. stderr:" >&2
  cat "$STDERR_LOG" >&2 || true
  exit 1
fi

TOOL_COUNT="$(printf '%s' "$RAW_OUTPUT" | python3 -c '
import json
import sys

# Any JSON-RPC error frame is reported, not just a missing id=3: a broken
# handshake shows up as an error on id=1/id=2, and blaming "no tools/list
# response" for it sent the last investigation to the wrong end of the
# exchange. Errors go to a side file so the caller can quote them.
count = None
errors = []
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        msg = json.loads(line)
    except json.JSONDecodeError:
        continue
    if "error" in msg:
        errors.append(
            "  id={} code={} message={}".format(
                msg.get("id"),
                msg["error"].get("code"),
                msg["error"].get("message"),
            )
        )
    if msg.get("id") == 3 and "result" in msg:
        count = len(msg["result"].get("tools", []))

with open(sys.argv[1], "w") as fh:
    fh.write("\n".join(errors))

print("NONE" if count is None else count)
' "$PROTOCOL_ERRORS")"

# A protocol error is a failure even when tools/list happens to answer: it
# means the container rejected a frame this script sent, and the last time
# that was tolerated it made the gate intermittent rather than red.
if [[ -s "$PROTOCOL_ERRORS" ]]; then
  echo "docker_smoke: FAIL — the container returned JSON-RPC error frames:" >&2
  cat "$PROTOCOL_ERRORS" >&2
  echo "--- container stderr ---" >&2
  cat "$STDERR_LOG" >&2 || true
  exit 1
fi

if [[ "$TOOL_COUNT" == "NONE" || -z "$TOOL_COUNT" ]]; then
  echo "docker_smoke: FAIL — no valid tools/list response (id=3) found in container stdout." >&2
  echo "--- raw stdout ---" >&2
  printf '%s\n' "$RAW_OUTPUT" >&2
  echo "--- stderr ---" >&2
  cat "$STDERR_LOG" >&2 || true
  exit 1
fi

if [[ "$TOOL_COUNT" -lt "$MIN_TOOL_COUNT" ]]; then
  echo "docker_smoke: FAIL — bare-container tools/list returned ${TOOL_COUNT} tools, expected >= ${MIN_TOOL_COUNT}." >&2
  echo "This is the exact regression fixed in commit 5d71069c (fix/bare-container-contract)." >&2
  exit 1
fi

echo "docker_smoke: PASS — bare-container tools/list returned ${TOOL_COUNT} tools (>= ${MIN_TOOL_COUNT})." >&2
exit 0
