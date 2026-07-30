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

# source: tests_py/test_main.py::TestMain::test_standalone_baseline_is_52_tools
# — the 52 standalone tools registered with zero upstream MCP servers
# reachable (codebase=False, prd=False): 49 re-derived 2026-07-12 via a live
# `docker run` + `uv run hypermnesia-mcp` round-trip (fix/bare-container-
# contract root-cause report), + `wiki_migrate` (FS→PG wiki parity), +
# `check_setup` (issue #115), + `ingest_document` (issue #192). Boy-scout
# fix 2026-07-30: this was still 49, citing a test name
# (test_standalone_baseline_is_49_tools) that no longer exists — the gate's
# floor was silently weaker than the true baseline for three tools' worth
# of regression headroom. `>=` guards against future regression without
# requiring an edit here every time a tool is added.
MIN_TOOL_COUNT="${CORTEX_SMOKE_MIN_TOOLS:-52}"
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
RAW_OUTPUT_FILE="$(mktemp "${TMPDIR:-/tmp}/docker_smoke_stdout.XXXXXX")"
# -u: name only, no file created — `docker run --cidfile` refuses to start
# if its target path already exists (mktemp's normal behavior creates an
# empty file, which would trip that check).
CID_FILE="$(mktemp -u "${TMPDIR:-/tmp}/docker_smoke_cid.XXXXXX")"
trap 'rm -f "$STDERR_LOG" "$PROTOCOL_ERRORS" "$RAW_OUTPUT_FILE" "$CID_FILE"' EXIT

# source: 60s is not new here — it is the SAME budget this script already
# used for its `timeout 60` / `gtimeout 60` wrapper before this change;
# named once so the watchdog below (which replaces that wrapper — see the
# measurement note) does not carry a second copy of the same literal.
DOCKER_RUN_TIMEOUT_SECONDS=60

# Portable timeout for the CLIENT side (image pull, auth, daemon
# connection): GNU coreutils `timeout` ships on ubuntu-latest (GitHub
# Actions runner) but not on macOS by default (`gtimeout` from `brew
# install coreutils` is the local-dev equivalent). Falls back to no
# CLIENT-side wrapper when neither exists — the watchdog below still
# bounds the CONTAINER side either way (see the next comment).
TIMEOUT_CMD=""
if command -v timeout >/dev/null 2>&1; then
  TIMEOUT_CMD="timeout ${DOCKER_RUN_TIMEOUT_SECONDS}"
elif command -v gtimeout >/dev/null 2>&1; then
  TIMEOUT_CMD="gtimeout ${DOCKER_RUN_TIMEOUT_SECONDS}"
fi

# `timeout`/`gtimeout` alone is NOT a sufficient bound for a hung
# CONTAINER: measured 2026-07-30 against a deliberately hanging test image
# (`ENTRYPOINT sh -c "sleep infinity"`) that `gtimeout 5 docker run --rm -i
# <image>` did NOT return even ~30s past its 5s deadline, and the container
# was still `docker ps`-visible afterward — `timeout`'s SIGTERM reaches the
# `docker run` CLIENT process, but that process does not reliably forward
# it to a CONTAINER blocked on unrelated work (this repo's Docker Desktop
# 29.1.4; not re-verified against every Docker version). `docker kill
# <container-id>` (via --cidfile) IS the mechanism measured to stop the
# container immediately — the watchdog below does that, uniformly on every
# platform, IN ADDITION to $TIMEOUT_CMD (which still helps bound a
# CLIENT-side hang, e.g. before any container exists to `docker kill`).
# This is a deadline (a worst-case bound on a single run), not a retry loop
# — it fires at most once, only as a last-resort kill switch, and never
# re-attempts the request.
printf '%s' "$REQUESTS" | $TIMEOUT_CMD docker run --rm -i --cidfile="$CID_FILE" "$IMAGE" >"$RAW_OUTPUT_FILE" 2>"$STDERR_LOG" &
DOCKER_RUN_PID=$!
(
  sleep "$DOCKER_RUN_TIMEOUT_SECONDS"
  if [[ -f "$CID_FILE" ]]; then
    docker kill "$(cat "$CID_FILE")" >/dev/null 2>&1 || true
  else
    # No container ever started (client-side hang) — fall back to signaling
    # the client process directly.
    kill "$DOCKER_RUN_PID" 2>/dev/null || true
  fi
) &
WATCHDOG_PID=$!
wait "$DOCKER_RUN_PID" 2>/dev/null || true
kill "$WATCHDOG_PID" 2>/dev/null || true
wait "$WATCHDOG_PID" 2>/dev/null || true
RAW_OUTPUT="$(cat "$RAW_OUTPUT_FILE")"

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
