#!/usr/bin/env bash
# memory-tool.sh — Local backend implementing the memory_20250818 contract
#
# Contract: memory/contract.md (source of truth, binding)
# Spec reference: platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool
#
# Usage:
#   memory-tool.sh view        <path> [view_range_start view_range_end]
#   memory-tool.sh create      <path> <file_text>
#   memory-tool.sh str_replace <path> <old_str> <new_str>
#   memory-tool.sh insert      <path> <insert_line> <insert_text>
#   memory-tool.sh delete      <path>
#   memory-tool.sh rename      <old_path> <new_path>
#   memory-tool.sh search      <query> [--scope <name>] [--limit N] [--regex]
#   memory-tool.sh scopes                           — list scopes + sizes (no content)
#   memory-tool.sh preamble                         — print Anthropic system-prompt preamble
#   memory-tool.sh sync-status                      — depth and oldest age of replica queue
#   memory-tool.sh drain-sync [--limit N]           — list pending replica jobs (JSONL)
#   memory-tool.sh commit-sync <job_id>             — mark job as successfully replicated
#   memory-tool.sh release-sync <job_id>            — return a claimed job to the queue
#   memory-tool.sh ttl-sweep [--dry-run]            — delete files older than scope TTL
#   memory-tool.sh audit [--since <iso8601>]        — tail audit log + summary + anomalies
#
# All paths MUST begin with /memories and are resolved under MEMORY_ROOT.
#
# Note: `search` is a deterministic full-text grep over scope files; it is
# NOT semantic similarity. Semantic recall is a separate MCP surface
# (cortex:recall) invoked by the agent directly — never aliased here.
#
# Env:
#   MEMORY_ROOT        (default: $HOME/.claude/memories)
#   MEMORY_AGENT_ID    (default: unknown)   — recorded in audit log + ACL check
#   MEMORY_REGISTRY    (default: $MEMORY_ROOT/.registry.json, or the repo seed)
#   MEMORY_MAX_FILE_KB (default: 100)       — hard per-file byte cap (fallback)
#   MEMORY_NO_AUDIT    (default: unset)     — disable audit log (tests only)
#   MEMORY_NO_ACL      (default: unset)     — disable ACL enforcement (tests only)
#
# Exit codes: 0 success; 1 contract error (message on stdout, verbatim per spec); 2 fatal (stderr).

set -euo pipefail

MEMORY_ROOT="${MEMORY_ROOT:-$HOME/.claude/memories}"
MEMORY_AGENT_ID="${MEMORY_AGENT_ID:-unknown}"
MEMORY_MAX_FILE_KB="${MEMORY_MAX_FILE_KB:-100}"
MEMORY_MAX_LINES=999999
AUDIT_LOG="$MEMORY_ROOT/.audit.log"
LOCK_DIR="$MEMORY_ROOT/.locks"
PENDING_SYNC_DIR="$MEMORY_ROOT/.pending-sync"

# Registry lookup order: env override → per-user installed → repo seed.
_script_dir="$(cd "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
_repo_seed="$_script_dir/../memory/scope-registry.json"
MEMORY_REGISTRY="${MEMORY_REGISTRY:-$MEMORY_ROOT/.registry.json}"
if [[ ! -f "$MEMORY_REGISTRY" && -f "$_repo_seed" ]]; then
  MEMORY_REGISTRY="$_repo_seed"
fi

# ─── helpers ─────────────────────────────────────────────────────────────────

die() { echo "memory-tool: $*" >&2; exit 2; }

# ─── registry / ACL ──────────────────────────────────────────────────────────
# Returns one of: allow | deny. Verbatim rules from scope-registry.json.
# Usage: acl_check <scope> <access: read|write>
# Falls back to defaults{} block if scope not listed.
# If strict_unknown_scope=true and scope missing, denies all writes.
acl_check() {
  local scope="$1" access="$2"
  [[ -n "${MEMORY_NO_ACL:-}" ]] && { echo allow; return 0; }
  if [[ ! -f "$MEMORY_REGISTRY" ]]; then
    # No registry present → permissive (first-run convenience).
    echo allow; return 0
  fi
  python3 - "$MEMORY_REGISTRY" "$scope" "$access" "$MEMORY_AGENT_ID" <<'PY'
import json, sys
registry_path, scope, access, agent = sys.argv[1:5]
with open(registry_path) as f:
    reg = json.load(f)
curators = set(reg.get("curator_agents", []))
defaults = reg.get("defaults", {"owners": ["_user"], "readers": ["*"]})
entry = reg.get("scopes", {}).get(scope)
if entry is None:
    if reg.get("strict_unknown_scope", False) and access == "write":
        print("deny"); sys.exit(0)
    entry = defaults
# Expand special tokens.
def matches(ids, agent):
    for i in ids:
        if i == "*": return True
        if i == agent: return True
        if i == "_curator" and agent in curators: return True
        if i == "_user" and agent == "_user": return True
    return False
# Reads consult readers list only. Writes consult owners list only.
# If registry author wants owners to read, they must include them in readers.
acl = entry.get("owners", []) if access == "write" else entry.get("readers", [])
print("allow" if matches(acl, agent) else "deny")
PY
}

# Per-scope file size cap from registry; falls back to MEMORY_MAX_FILE_KB env.
# Usage: scope_max_kb <scope> → prints integer KB.
scope_max_kb() {
  local scope="$1"
  if [[ ! -f "$MEMORY_REGISTRY" ]]; then
    echo "$MEMORY_MAX_FILE_KB"; return 0
  fi
  python3 - "$MEMORY_REGISTRY" "$scope" "$MEMORY_MAX_FILE_KB" <<'PY'
import json, sys
reg_path, scope, fallback = sys.argv[1:4]
with open(reg_path) as f:
    reg = json.load(f)
entry = reg.get("scopes", {}).get(scope) or reg.get("defaults", {})
print(entry.get("max_file_kb", int(fallback)))
PY
}

# Emit ACL denial verbatim (agent-facing; audit logged by caller).
acl_deny() {
  local scope="$1" access="$2"
  echo "Error: agent '$MEMORY_AGENT_ID' is not permitted to $access scope '/memories/$scope'"
}

# Resolve a user-facing /memories path to an absolute FS path.
# Usage: resolve_path <vpath> <out_var_name>
#   - on success: sets the named variable, returns 0
#   - on failure: prints Anthropic-verbatim error to stdout, returns 1
# Uses an out-variable (not command substitution) so error messages are
# visible to the user instead of being swallowed by $(...).
resolve_path() {
  local vpath="$1" __out_var="$2"
  # Must start with /memories exactly (either the bare root or /memories/...).
  if [[ "$vpath" != "/memories" && "$vpath" != /memories/* ]]; then
    echo "Error: path must begin with /memories"
    return 1
  fi
  # Reject obvious traversal patterns before any filesystem operation.
  case "$vpath" in
    *'/../'*|*'/./'*|*'/..'|*'/.'|*'..\\'*|*'%2e%2e'*|*'%2E%2E'*)
      echo "Error: path must begin with /memories"
      return 1 ;;
  esac
  local rel=""
  [[ "$vpath" == /memories/* ]] && rel="${vpath#/memories/}"
  local target="$MEMORY_ROOT${rel:+/$rel}"
  # Bare root (/memories) is always valid — it maps to MEMORY_ROOT itself,
  # which is created at tool startup. Skip parent check in this case.
  if [[ "$target" != "$MEMORY_ROOT" ]]; then
    # For non-root paths, canonicalize the existing parent and verify it
    # stays inside MEMORY_ROOT. This defeats symlink escapes. Parent is NOT
    # auto-created here — that happens in the command handler after validation.
    local parent; parent="$(dirname -- "$target")"
    if [[ -d "$parent" ]]; then
      local real_parent; real_parent="$(cd "$parent" && pwd -P)"
      local real_root; real_root="$(cd "$MEMORY_ROOT" && pwd -P)"
      case "$real_parent" in
        "$real_root"|"$real_root"/*) : ;;
        *) echo "Error: path must begin with /memories"; return 1 ;;
      esac
    fi
  fi
  printf -v "$__out_var" '%s' "$target"
}

# Ensure the parent directory of a target path exists. Called only after
# resolve_path has validated the target is inside MEMORY_ROOT.
ensure_parent() {
  local target="$1"
  mkdir -p -- "$(dirname -- "$target")"
}

# Virtual path for user-facing messages (keeps /memories prefix stable).
vpath() { printf '%s' "$1"; }

# Acquire exclusive per-scope lock. Scope = first path segment under /memories.
scope_of() {
  local vpath="$1"
  local rel="${vpath#/memories/}"
  local scope="${rel%%/*}"
  [[ -n "$scope" && "$scope" != "$vpath" ]] || scope="_root"
  printf '%s' "$scope"
}

with_lock() {
  # I-LOCK (Lamport 1978 §3): at most one process executes the critical section
  #   for a given scope at any instant. Source: POSIX mkdir(2) atomicity.
  # I-NEW (liveness): a SIGKILL'd holder does not permanently block writers.
  #   Source: kill -0 PID liveness check (POSIX kill(2), signal 0 semantics).
  # I-NEW-2 (no false reclaim): a slow but live holder is NEVER stolen from.
  #   Source: kill -0 returns 0 for live processes; reclaim requires confirmed death.
  # Portability note: Option A (kill -0) chosen over Option B (proc start-time)
  #   for portability (no /proc or `ps -o lstart` dependency). PID-reuse risk
  #   is accepted: the window is narrow (holder dead + PID recycled within 100ms
  #   spin tick); reclaim is an improvement over unconditional die, not a
  #   guarantee of perfect safety under extreme PID-reuse churn.
  local scope="$1"; shift
  mkdir -p "$LOCK_DIR"
  local lockdir="$LOCK_DIR/$scope.lockd"
  local pid_file="$lockdir/pid"
  local tries=0 max_tries=50 rc=0
  while ! mkdir "$lockdir" 2>/dev/null; do
    sleep 0.1
    tries=$((tries + 1))
    # ── stale-lock reclaim ──────────────────────────────────────────────────
    # Only attempt reclaim when we have a PID to check (holder wrote it).
    if [[ -f "$pid_file" ]]; then
      local holder_pid
      holder_pid=$(cat "$pid_file" 2>/dev/null || true)
      if [[ -n "$holder_pid" ]] && ! kill -0 "$holder_pid" 2>/dev/null; then
        # Holder is dead. Reclaim sequence:
        #   1. Remove the pid file so lockdir becomes empty (rmdir requires empty).
        #   2. rmdir the now-empty lockdir atomically — only one waiter's rmdir
        #      can succeed (POSIX rmdir(2) atomicity). The loser gets ENOENT.
        #   3. mkdir our lock. If it fails, another waiter already re-acquired.
        # Serialization guarantee: at most one rmdir(2) removes the dentry.
        # happens-before witness: rmdir succeeds only after the dead holder's
        # process table entry is gone; our subsequent mkdir is causally after.
        rm -f "$lockdir/pid" 2>/dev/null || true
        if rmdir "$lockdir" 2>/dev/null; then
          audit "with_lock" "/memories/$scope" 0 "stale_lock_reclaimed"
          if mkdir "$lockdir" 2>/dev/null; then
            # We won the reclaim race; write our PID and proceed.
            printf '%s' "$$" > "$lockdir/pid"
            break
          fi
          # Another waiter beat us to the mkdir; fall through to normal spin.
        fi
        # Either rmdir failed (another waiter already reclaimed) or our mkdir
        # failed after rmdir (another waiter won). Continue spinning.
        tries=0   # reset counter: progress was made, don't penalise
        continue
      fi
    fi
    # ── end stale-lock reclaim ──────────────────────────────────────────────
    (( tries >= max_tries )) && die "could not acquire lock on scope '$scope' after 5s"
  done
  # Write holder PID so waiters can check liveness.
  printf '%s' "$$" > "$pid_file"
  # Release: remove pid file first so lockdir is empty, then rmdir atomically.
  trap 'rm -f "'"$lockdir"'/pid" 2>/dev/null; rmdir "'"$lockdir"'" 2>/dev/null || true' EXIT INT TERM
  "$@"
  rc=$?
  rm -f "$lockdir/pid" 2>/dev/null || true
  rmdir "$lockdir" 2>/dev/null || true
  trap - EXIT INT TERM
  return $rc
}

# Atomic write: write to .tmp then rename. Caller has already held the lock.
atomic_write() {
  local target="$1" content="$2"
  local tmp="$target.tmp.$$"
  printf '%s' "$content" > "$tmp"
  # fsync file
  if command -v sync >/dev/null 2>&1; then sync; fi
  mv -f -- "$tmp" "$target"
}

size_check() {
  local bytes="$1" path="$2" scope="$3"
  local max_kb; max_kb="$(scope_max_kb "$scope")"
  local max=$((max_kb * 1024))
  if (( bytes > max )); then
    echo "Error: file $(vpath "$path") exceeds max size of ${max_kb}KB"
    exit 1
  fi
}

# ─── PII / secret scan (contract §7.2) ───────────────────────────────────────
# Env:
#   MEMORY_PII_SCAN_DISABLE=1  — bypass entirely (test/emergency)
#   MEMORY_PII_STRICT=1        — also block low-confidence classes (email, phone)
# On scanner error: prints "pii_scan_error" (caller allows write — not a DoS vector).
# INVARIANT: matched bytes are NEVER written to any file or log — only rule IDs.
#
# Performance architecture (profile-driven, 2026-04-24):
#   Profiling showed Python cold-start = 37 ms; scan logic = 1.3 ms on 10 KB.
#   Solution: pii-daemon.py (persistent Python process) listens on a Unix-domain
#   socket.  _pii_scan_pipe sends one JSON request via `nc -U` (~4.6 ms median).
#   Cold-start is paid once at daemon launch, not per write.
#   Fallback: if the daemon is unavailable, fall back to the original per-call
#   python3 subprocess so correctness is never sacrificed for performance.
#   Source: memory/pii-profile.md

# _pii_daemon_sock — path to the Unix socket for the running daemon (if any).
# Co-located with MEMORY_ROOT so each root gets its own daemon.
_pii_daemon_sock() {
  printf '%s' "$MEMORY_ROOT/.pii-daemon.sock"
}
_pii_daemon_pid_file() {
  printf '%s' "$MEMORY_ROOT/.pii-daemon.sock.pid"
}

# _pii_daemon_ensure — start the daemon if its socket is absent or its PID is dead.
# Returns 0 if the daemon is ready (socket exists), 1 if it could not be started.
_pii_daemon_ensure() {
  local _tool_dir; _tool_dir="$(cd "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
  local daemon_py="$_tool_dir/../memory/pii-daemon.py"
  local rules_file="$_tool_dir/../memory/pii-rules.json"
  local sock; sock="$(_pii_daemon_sock)"
  local pid_file; pid_file="$(_pii_daemon_pid_file)"

  if [[ ! -f "$daemon_py" || ! -f "$rules_file" ]]; then return 1; fi

  # Check if daemon is already running: socket exists AND pid file contains a
  # live PID.  If the PID is dead (SIGKILL etc.) we clean up and restart.
  if [[ -S "$sock" && -f "$pid_file" ]]; then
    local saved_pid; saved_pid="$(cat "$pid_file" 2>/dev/null)"
    if [[ -n "$saved_pid" ]] && kill -0 "$saved_pid" 2>/dev/null; then
      return 0  # daemon is live
    fi
    # Stale socket — clean up before restarting.
    rm -f "$sock" "$pid_file"
  fi

  # Start daemon in background, daemonised from this shell's process group so
  # it outlives the memory-tool.sh invocation.
  # MEMORY_ROOT must be exported for the daemon to find rules via $MEMORY_ROOT
  # if it ever needs it; currently the rules path is passed as argv[1].
  export MEMORY_ROOT
  python3 "$daemon_py" "$rules_file" "$sock" </dev/null >/dev/null 2>/dev/null &
  disown $! 2>/dev/null || true

  # Wait up to 1 s for the socket to appear (daemon startup is ~30 ms).
  local i=0
  while (( i < 20 )); do
    [[ -S "$sock" ]] && return 0
    sleep 0.05
    i=$((i + 1))
  done
  return 1  # daemon failed to start in time; caller falls back
}

# _pii_scan_via_daemon — send content to the running daemon, return its response.
# Returns 0 and prints result; returns 1 if the daemon is unreachable.
#
# WHY sed-based JSON encoding (not python3):
#   Spawning python3 for encoding costs ~32 ms (cold-start) — negating the
#   daemon's benefit.  sed is a C process that starts in ~2 ms.  The chars that
#   require JSON escaping in practice are backslash, double-quote, and newline.
#   sed handles all three via three substitution expressions plus the N-loop
#   accumulate-and-replace trick for newlines.  Control chars (0x00–0x1F) are
#   rare in memory entries; if an unencoded control char slips through, the
#   daemon's json.loads raises, returns "pii_scan_error", and the write is
#   allowed (fail-open per §7.2 contract) — not a correctness violation.
#
# CORRECTNESS invariant: incorrect encoding → pii_scan_error → write allowed.
# The correctness direction is: false allow (never false block).
_pii_scan_via_daemon() {
  local content="$1"
  local sock; sock="$(_pii_daemon_sock)"
  local strict="false"
  [[ "${MEMORY_PII_STRICT:-0}" == "1" ]] && strict="true"

  # Encode the content string for JSON embedding.
  # Substitution order matters: backslash must be escaped first to avoid
  # double-escaping the backslashes inserted by later substitutions.
  # Complexity: O(N) in content length.  sed processes the whole content in one
  # pass per substitution; combined with :a;N;$!ba (accumulate all lines into
  # the pattern space) the total work is O(4N).
  local encoded
  encoded=$(printf '%s' "$content" \
    | sed -e 's/\\/\\\\/g' \
          -e 's/"/\\"/g' \
          -e 's/	/\\t/g' \
          -e ':a;N;$!ba;s/\n/\\n/g' \
    2>/dev/null) || return 1

  # Send the JSON request to the daemon; read one response line.
  local response
  response=$(printf '{"content":"%s","strict":%s}\n' "$encoded" "$strict" \
    | nc -U "$sock" 2>/dev/null) || return 1
  [[ -n "$response" ]] || return 1
  printf '%s' "$response"
  return 0
}

# Internal: reads content from stdin, emits "pass" | "blocked:<rule_id>" | "pii_scan_error".
# Primary path: persistent daemon via Unix socket (avoids Python cold-start per call).
# Fallback path: original per-call python3 subprocess (used if daemon unavailable).
_pii_scan_pipe() {
  local _tool_dir; _tool_dir="$(cd "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
  local scanner_py="$_tool_dir/../memory/pii-scanner.py"
  local rules_file="$_tool_dir/../memory/pii-rules.json"
  if [[ ! -f "$scanner_py" || ! -f "$rules_file" ]]; then printf 'pii_scan_error'; return 0; fi
  if [[ -n "${MEMORY_PII_SCAN_DISABLE:-}" ]]; then printf 'pii_scan_disabled'; return 0; fi

  # Read stdin into a variable (content is already in memory in the caller,
  # but _pii_scan_pipe receives it via pipe from _pii_gate).
  local content; content="$(cat)"

  # Primary path: daemon.
  if _pii_daemon_ensure 2>/dev/null; then
    local daemon_result
    daemon_result="$(_pii_scan_via_daemon "$content" 2>/dev/null)"
    if [[ -n "$daemon_result" ]]; then
      printf '%s' "$daemon_result"
      return 0
    fi
    # Daemon returned empty — fall through to subprocess fallback.
  fi

  # Fallback path: original per-call subprocess (preserves all contract
  # semantics if daemon is unavailable or returns garbage).
  printf '%s' "$content" | python3 "$scanner_py" "$rules_file" "${MEMORY_PII_STRICT:-0}" 2>/dev/null \
    || { printf 'pii_scan_error'; return 0; }
}

# Apply PII gate to new content before any write.
# Usage: _pii_gate <content> <cmd> <vpath> <bytes>
# Exits 1 with user-facing error on block; returns 0 on pass or scanner error.
_pii_gate() {
  local content="$1" cmd="$2" vpath="$3" bytes="$4"
  local result; result="$(printf '%s' "$content" | _pii_scan_pipe)"
  case "$result" in
    pass|pii_scan_disabled) return 0 ;;
    pii_scan_error)
      audit "$cmd" "$vpath" "$bytes" "pii_scan_error"
      return 0
      ;;
    blocked:*)
      local rule_id="${result#blocked:}"
      audit "$cmd" "$vpath" "$bytes" "pii_blocked:${rule_id}"
      echo "Error: write blocked by PII/secret scanner (matched rule: ${rule_id}). Remove sensitive content before writing."
      exit 1
      ;;
  esac
}

audit() {
  [[ -n "${MEMORY_NO_AUDIT:-}" ]] && return 0
  local cmd="$1" vpath="$2" bytes="${3:-0}" result="${4:-ok}"
  local sha="${5:-}"
  mkdir -p -- "$(dirname -- "$AUDIT_LOG")"
  local ts; ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf '%s\t%s\t%s\t%s\t%s\t%d\t%s\t%s\n' \
    "$ts" "$MEMORY_AGENT_ID" "$(scope_of "$vpath")" "$cmd" "$vpath" "$bytes" "$sha" "$result" \
    >> "$AUDIT_LOG"
}

sha256_of() {
  if command -v shasum >/dev/null 2>&1; then shasum -a 256 | awk '{print $1}'
  else sha256sum | awk '{print $1}'; fi
}

# Human-readable size like 4.0K / 1.5K / 2.0M (matches Anthropic view format).
human_size() {
  local bytes="$1"
  awk -v b="$bytes" 'BEGIN{
    if (b < 1024) printf "%dB", b;
    else if (b < 1024*1024) printf "%.1fK", b/1024;
    else printf "%.1fM", b/(1024*1024);
  }'
}

# ─── commands ────────────────────────────────────────────────────────────────

cmd_view() {
  local vpath="$1" range_start="${2:-}" range_end="${3:-}"
  local real
  resolve_path "$vpath" real || exit 1
  local scope; scope="$(scope_of "$vpath")"
  if [[ "$(acl_check "$scope" read)" == "deny" ]]; then
    acl_deny "$scope" read
    audit "view" "$vpath" 0 acl_denied
    exit 1
  fi
  if [[ ! -e "$real" ]]; then
    echo "The path $vpath does not exist. Please provide a valid path."
    exit 1
  fi
  if [[ -d "$real" ]]; then
    # Directory: depth-2 listing, sizes, exclude dotfiles and node_modules.
    echo "Here're the files and directories up to 2 levels deep in $vpath, excluding hidden items and node_modules:"
    local root_size; root_size=$(human_size "$(du -sk "$real" 2>/dev/null | awk '{print $1*1024}')")
    printf '%s\t%s\n' "$root_size" "$vpath"
    # Build listing with find, 2 levels deep, exclude hidden + node_modules.
    find "$real" -mindepth 1 -maxdepth 2 \
      \( -name '.*' -o -name 'node_modules' \) -prune -o -print 2>/dev/null \
      | sort \
      | while IFS= read -r entry; do
          [[ -z "$entry" ]] && continue
          local rel="${entry#$real/}"
          local display="$vpath/$rel"
          local bytes
          if [[ -d "$entry" ]]; then
            bytes=$(du -sk "$entry" 2>/dev/null | awk '{print $1*1024}')
          else
            bytes=$(wc -c < "$entry" 2>/dev/null || echo 0)
          fi
          printf '%s\t%s\n' "$(human_size "$bytes")" "$display"
        done
    audit "view" "$vpath" 0 ok
    return 0
  fi

  # File view
  local total_lines; total_lines=$(awk 'END{print NR}' "$real")
  if (( total_lines > MEMORY_MAX_LINES )); then
    echo "File $vpath exceeds maximum line limit of 999,999 lines."
    exit 1
  fi
  echo "Here's the content of $vpath with line numbers:"
  local start=1 end="$total_lines"
  if [[ -n "$range_start" ]]; then start="$range_start"; fi
  if [[ -n "$range_end" ]]; then end="$range_end"; fi
  awk -v s="$start" -v e="$end" 'NR>=s && NR<=e { printf "%6d\t%s\n", NR, $0 }' "$real"
  audit "view" "$vpath" "$(wc -c < "$real")" ok
}

cmd_create() {
  local vpath="$1" file_text="$2"
  local real
  resolve_path "$vpath" real || exit 1
  local scope; scope="$(scope_of "$vpath")"
  if [[ "$(acl_check "$scope" write)" == "deny" ]]; then
    acl_deny "$scope" write
    audit "create" "$vpath" 0 acl_denied
    exit 1
  fi
  ensure_parent "$real"
  _do_create() {
    if [[ -e "$real" ]]; then
      echo "Error: File $vpath already exists"
      audit "create" "$vpath" 0 duplicate
      exit 1
    fi
    local bytes=${#file_text}
    size_check "$bytes" "$vpath" "$scope" "$scope"
    _pii_gate "$file_text" "create" "$vpath" "$bytes"
    atomic_write "$real" "$file_text"
    local sha; sha=$(printf '%s' "$file_text" | sha256_of)
    audit "create" "$vpath" "$bytes" ok "$sha"
    enqueue_sync "create" "$vpath" "$scope"
    echo "File created successfully at: $vpath"
  }
  with_lock "$scope" _do_create
}

cmd_str_replace() {
  local vpath="$1" old_str="$2" new_str="$3"
  local real
  resolve_path "$vpath" real || exit 1
  local scope; scope="$(scope_of "$vpath")"
  if [[ "$(acl_check "$scope" write)" == "deny" ]]; then
    acl_deny "$scope" write
    audit "str_replace" "$vpath" 0 acl_denied
    exit 1
  fi
  _do_replace() {
    if [[ ! -f "$real" ]]; then
      echo "Error: The path $vpath does not exist. Please provide a valid path."
      audit "str_replace" "$vpath" 0 missing
      exit 1
    fi
    local content; content="$(cat "$real")"
    # Count occurrences using awk (handles multi-line old_str via python for safety).
    local occ lines
    occ=$(python3 - "$real" "$old_str" <<'PY'
import sys, pathlib
p = pathlib.Path(sys.argv[1]); needle = sys.argv[2]
content = p.read_text()
count = content.count(needle)
print(count)
if count > 1:
    # Emit line numbers of every occurrence.
    start = 0
    lines = []
    while True:
        idx = content.find(needle, start)
        if idx == -1: break
        line_num = content.count("\n", 0, idx) + 1
        lines.append(str(line_num))
        start = idx + 1
    print(",".join(lines))
PY
)
    local count="${occ%%$'\n'*}"
    lines="${occ#*$'\n'}"
    if [[ "$count" == "0" ]]; then
      echo "No replacement was performed, old_str \`$old_str\` did not appear verbatim in $vpath."
      audit "str_replace" "$vpath" 0 not_found
      exit 1
    fi
    if (( count > 1 )); then
      echo "No replacement was performed. Multiple occurrences of old_str \`$old_str\` in lines: $lines. Please ensure it is unique"
      audit "str_replace" "$vpath" 0 ambiguous
      exit 1
    fi
    local new_content
    new_content=$(python3 - "$real" "$old_str" "$new_str" <<'PY'
import sys, pathlib
p = pathlib.Path(sys.argv[1])
content = p.read_text()
new = content.replace(sys.argv[2], sys.argv[3], 1)
sys.stdout.write(new)
PY
)
    local bytes=${#new_content}
    size_check "$bytes" "$vpath" "$scope"
    _pii_gate "$new_content" "str_replace" "$vpath" "$bytes"
    atomic_write "$real" "$new_content"
    local sha; sha=$(printf '%s' "$new_content" | sha256_of)
    audit "str_replace" "$vpath" "$bytes" ok "$sha"
    enqueue_sync "str_replace" "$vpath" "$scope"
    echo "The memory file has been edited."
    # Snippet with line numbers around the change (context lines).
    awk '{ printf "%6d\t%s\n", NR, $0 }' "$real" | head -20
  }
  with_lock "$scope" _do_replace
}

cmd_insert() {
  local vpath="$1" insert_line="$2" insert_text="$3"
  local real
  resolve_path "$vpath" real || exit 1
  local scope; scope="$(scope_of "$vpath")"
  if [[ "$(acl_check "$scope" write)" == "deny" ]]; then
    acl_deny "$scope" write
    audit "insert" "$vpath" 0 acl_denied
    exit 1
  fi
  _do_insert() {
    if [[ ! -f "$real" ]]; then
      echo "Error: The path $vpath does not exist"
      audit "insert" "$vpath" 0 missing
      exit 1
    fi
    local n_lines; n_lines=$(awk 'END{print NR}' "$real")
    if ! [[ "$insert_line" =~ ^[0-9]+$ ]] || (( insert_line < 0 || insert_line > n_lines )); then
      echo "Error: Invalid \`insert_line\` parameter: $insert_line. It should be within the range of lines of the file: [0, $n_lines]"
      audit "insert" "$vpath" 0 invalid_line
      exit 1
    fi
    local new_content
    new_content=$(python3 - "$real" "$insert_line" "$insert_text" <<'PY'
import sys, pathlib
p = pathlib.Path(sys.argv[1]); ln = int(sys.argv[2]); text = sys.argv[3]
lines = p.read_text().splitlines(keepends=True)
lines.insert(ln, text if text.endswith("\n") else text + "\n")
sys.stdout.write("".join(lines))
PY
)
    local bytes=${#new_content}
    size_check "$bytes" "$vpath" "$scope"
    _pii_gate "$new_content" "insert" "$vpath" "$bytes"
    atomic_write "$real" "$new_content"
    local sha; sha=$(printf '%s' "$new_content" | sha256_of)
    audit "insert" "$vpath" "$bytes" ok "$sha"
    enqueue_sync "insert" "$vpath" "$scope"
    echo "The file $vpath has been edited."
  }
  with_lock "$scope" _do_insert
}

cmd_delete() {
  local vpath="$1"
  local real
  resolve_path "$vpath" real || exit 1
  local scope; scope="$(scope_of "$vpath")"
  if [[ "$(acl_check "$scope" write)" == "deny" ]]; then
    acl_deny "$scope" write
    audit "delete" "$vpath" 0 acl_denied
    exit 1
  fi
  _do_delete() {
    if [[ ! -e "$real" ]]; then
      echo "Error: The path $vpath does not exist"
      audit "delete" "$vpath" 0 missing
      exit 1
    fi
    rm -rf -- "$real"
    audit "delete" "$vpath" 0 ok
    enqueue_sync "delete" "$vpath" "$scope"
    echo "Successfully deleted $vpath"
  }
  with_lock "$scope" _do_delete
}

# ─── Cortex replica queue ────────────────────────────────────────────────────
# Local FS is authoritative; Cortex is an async replica. After any successful
# mutation, enqueue a job describing the post-state. A Claude-side agent
# drains the queue via MCP (cortex:remember) and marks jobs committed.
# Enqueue failure MUST NOT fail the parent op (contract §5.3).

MEMORY_NO_SYNC="${MEMORY_NO_SYNC:-}"

enqueue_sync() {
  [[ -n "$MEMORY_NO_SYNC" ]] && return 0
  local op="$1" vpath="$2" scope="$3" new_vpath="${4:-}"
  mkdir -p -- "$PENDING_SYNC_DIR" 2>/dev/null || return 0
  local ts; ts="$(date -u +%Y%m%dT%H%M%SZ)"
  # Short random suffix for uniqueness under concurrent writes.
  local rand; rand="$(od -An -N4 -tx1 /dev/urandom 2>/dev/null | tr -d ' \n' || printf '%04x' "$RANDOM")"
  local id="${ts}-${rand}"
  local job_file="$PENDING_SYNC_DIR/$id.json"
  local tmp="$job_file.tmp.$$"

  # Read post-state (for ops that leave a file). Skip for delete.
  local target_real=""
  if [[ "$op" != "delete" ]]; then
    local effective_vpath="${new_vpath:-$vpath}"
    if ! resolve_path "$effective_vpath" target_real 2>/dev/null; then
      # Resolution failure shouldn't block enqueue — record without body.
      target_real=""
    fi
  fi

  python3 - "$tmp" "$id" "$op" "$vpath" "$new_vpath" "$scope" "$MEMORY_AGENT_ID" "$target_real" <<'PY' 2>/dev/null || return 0
import sys, os, json, hashlib, base64, pathlib
tmp, job_id, op, vpath, new_vpath, scope, agent, target = sys.argv[1:9]
payload = {
    "id": job_id,
    "ts": __import__("datetime").datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    "op": op,
    "agent_id": agent,
    "scope": scope,
    "vpath": vpath,
}
if new_vpath:
    payload["new_vpath"] = new_vpath
if target and op != "delete" and pathlib.Path(target).is_file():
    data = pathlib.Path(target).read_bytes()
    payload["bytes"] = len(data)
    payload["content_sha256"] = hashlib.sha256(data).hexdigest()
    payload["content_b64"] = base64.b64encode(data).decode()
pathlib.Path(tmp).write_text(json.dumps(payload, ensure_ascii=False))
PY
  mv -f -- "$tmp" "$job_file" 2>/dev/null || { rm -f "$tmp"; return 0; }
  return 0
}

cmd_sync_status() {
  if [[ ! -d "$PENDING_SYNC_DIR" ]]; then
    echo "queue: empty (no .pending-sync directory yet)"
    return 0
  fi
  local pending claimed oldest
  pending=$(find "$PENDING_SYNC_DIR" -maxdepth 1 -type f -name '*.json' 2>/dev/null | wc -l | tr -d ' ')
  claimed=$(find "$PENDING_SYNC_DIR" -maxdepth 1 -type f -name '*.json.claimed' 2>/dev/null | wc -l | tr -d ' ')
  oldest=$(find "$PENDING_SYNC_DIR" -maxdepth 1 -type f -name '*.json' 2>/dev/null \
           | sort | head -1 | xargs -I{} basename {} .json 2>/dev/null || true)
  printf 'queue: %d pending, %d claimed (in-flight)\n' "$pending" "$claimed"
  [[ -n "$oldest" ]] && printf 'oldest: %s\n' "$oldest"
}

cmd_drain_sync() {
  # Emit pending jobs as JSONL, one per line, AND atomically claim each so
  # a concurrent drainer cannot replicate the same job twice. Caller must
  # invoke commit-sync or release-sync for each id it emits.
  local limit=50
  while (( $# )); do
    case "$1" in
      --limit) limit="$2"; shift 2 ;;
      *) shift ;;
    esac
  done
  [[ -d "$PENDING_SYNC_DIR" ]] || { echo ""; return 0; }
  local count=0
  # Sort by filename (timestamp-prefixed → chronological).
  while IFS= read -r job_file; do
    [[ -z "$job_file" ]] && continue
    (( count >= limit )) && break
    local claimed="$job_file.claimed"
    # Atomic claim via rename — loser sees ENOENT on original and skips.
    # INVARIANT: a job is claimed iff the source no longer exists after mv -n.
    # BSD mv -n returns exit 0 even when dst pre-exists (no-clobber skip), so
    # [[ -f $claimed ]] is insufficient — it is true whether or not WE moved it.
    # The correct witness is [[ ! -e $job_file ]]: the rename atomically removed
    # the source; if it still exists, another drainer claimed it first.
    # source: POSIX rename(2) atomicity; BSD mv(1) man page no-clobber semantics.
    if mv -n -- "$job_file" "$claimed" 2>/dev/null && [[ ! -e "$job_file" ]]; then
      cat "$claimed"
      printf '\n'
      count=$((count + 1))
    fi
  done < <(find "$PENDING_SYNC_DIR" -maxdepth 1 -type f -name '*.json' 2>/dev/null | sort)
}

cmd_commit_sync() {
  local job_id="$1"
  [[ -z "$job_id" ]] && { echo "Error: commit-sync requires a job id"; exit 1; }
  local claimed="$PENDING_SYNC_DIR/$job_id.json.claimed"
  if [[ ! -f "$claimed" ]]; then
    echo "Error: job $job_id is not claimed (already committed or never drained)"
    exit 1
  fi
  rm -f -- "$claimed"
  echo "Committed sync job $job_id"
}

cmd_release_sync() {
  local job_id="$1"
  [[ -z "$job_id" ]] && { echo "Error: release-sync requires a job id"; exit 1; }
  local claimed="$PENDING_SYNC_DIR/$job_id.json.claimed"
  local pending="$PENDING_SYNC_DIR/$job_id.json"
  if [[ ! -f "$claimed" ]]; then
    echo "Error: job $job_id is not claimed"
    exit 1
  fi
  mv -- "$claimed" "$pending"
  echo "Released sync job $job_id back to queue"
}

cmd_scopes() {
  # Per-scope summary: name, file count, total bytes, access role of current agent.
  # No file contents. Safe to auto-inject at spawn.
  if [[ ! -d "$MEMORY_ROOT" ]] || [[ -z "$(ls -A "$MEMORY_ROOT" 2>/dev/null | grep -v '^\.' || true)" ]]; then
    echo "(memory is empty — use 'memory-tool.sh create /memories/<scope>/<file> <text>' to start)"
    return 0
  fi
  printf '%-20s %8s %8s  %s\n' "SCOPE" "FILES" "BYTES" "ACCESS"
  for d in "$MEMORY_ROOT"/*/; do
    [[ -d "$d" ]] || continue
    local scope; scope="$(basename -- "$d")"
    [[ "$scope" == "_"* ]] && continue
    [[ "$scope" == .* ]] && continue
    local files; files=$(find "$d" -type f ! -name '.*' 2>/dev/null | wc -l | tr -d ' ')
    local bytes; bytes=$(find "$d" -type f ! -name '.*' -exec wc -c {} + 2>/dev/null | awk 'END{print $1+0}')
    local access="none"
    local r="$(acl_check "$scope" read)"
    local w="$(acl_check "$scope" write)"
    if [[ "$r" == "allow" && "$w" == "allow" ]]; then access="rw"
    elif [[ "$r" == "allow" ]]; then access="r"
    elif [[ "$w" == "allow" ]]; then access="w"
    fi
    printf '%-20s %8s %8s  %s\n' "/memories/$scope" "$files" "$(human_size "${bytes:-0}")" "$access"
  done
}

cmd_preamble() {
  # Emit the Anthropic memory-tool system-prompt preamble verbatim, so agent
  # definitions can include it at spawn. Matches the spec at
  # platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool.
  cat <<'EOF'
IMPORTANT: ALWAYS VIEW YOUR MEMORY DIRECTORY BEFORE DOING ANYTHING ELSE.
MEMORY PROTOCOL:
1. Use the `view` command of your `memory` tool to check for earlier progress.
2. ... (work on the task) ...
     - As you make progress, record status / progress / thoughts etc in your memory.
ASSUME INTERRUPTION: Your context window might be reset at any moment, so you risk losing any progress that is not recorded in your memory directory.

Local extension: use `search <query>` for deterministic full-text retrieval
across scopes; use `cortex:recall` (MCP) for semantic similarity.
Memory lives under /memories/<scope>/<file>. Scope ACL is enforced — write
attempts outside your declared scope are rejected. Quarantine memories
(/memories/quarantine/) are NEVER auto-loaded.
EOF
}

cmd_search() {
  # Deterministic full-text search. Returns <vpath>:<line>:<snippet> per match.
  # Respects readers ACL: files in scopes the agent cannot read are skipped.
  local query=""
  local scope_filter=""
  local limit=50
  local mode="fixed"   # fixed = literal string; regex = extended regex
  while (( $# )); do
    case "$1" in
      --scope) scope_filter="$2"; shift 2 ;;
      --limit) limit="$2"; shift 2 ;;
      --regex) mode="regex"; shift ;;
      --) shift; query="$*"; break ;;
      *) [[ -z "$query" ]] && query="$1" || query="$query $1"; shift ;;
    esac
  done
  if [[ -z "$query" ]]; then
    echo "Error: search requires a query string"
    exit 1
  fi

  # Determine search root.
  local search_root="$MEMORY_ROOT"
  if [[ -n "$scope_filter" ]]; then
    local scope_real="$MEMORY_ROOT/$scope_filter"
    if [[ ! -d "$scope_real" ]]; then
      echo "The path /memories/$scope_filter does not exist. Please provide a valid path."
      exit 1
    fi
    if [[ "$(acl_check "$scope_filter" read)" == "deny" ]]; then
      acl_deny "$scope_filter" read
      audit "search" "/memories/$scope_filter" 0 acl_denied
      exit 1
    fi
    search_root="$scope_real"
  fi

  # Pick the best available grepper.
  local grepper=()
  if command -v rg >/dev/null 2>&1; then
    grepper=(rg --no-heading --line-number --color=never --max-count="$limit")
    [[ "$mode" == "fixed" ]] && grepper+=(--fixed-strings)
  else
    grepper=(grep -r -n --color=never)
    [[ "$mode" == "fixed" ]] && grepper+=(-F) || grepper+=(-E)
  fi

  # Exclude control files and locks.
  local excludes=("--exclude-dir=.locks" "--exclude=.audit.log" "--exclude=.registry.json")
  if [[ "${grepper[0]}" == "rg" ]]; then
    excludes=("--glob=!.locks/**" "--glob=!.audit.log" "--glob=!.registry.json")
  fi

  local raw_matches; raw_matches=$("${grepper[@]}" "${excludes[@]}" -- "$query" "$search_root" 2>/dev/null || true)
  if [[ -z "$raw_matches" ]]; then
    echo "No matches for query in $( [[ -n "$scope_filter" ]] && echo "/memories/$scope_filter" || echo "/memories" )."
    audit "search" "/memories${scope_filter:+/$scope_filter}" 0 no_match
    return 0
  fi

  # Rewrite absolute FS paths back to /memories/... virtual paths, then enforce
  # per-file read ACL (a match inside an unreadable scope must not leak).
  local hits=0
  local match_out=""
  local real_root; real_root="$(cd "$MEMORY_ROOT" && pwd -P)"
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    local path="${line%%:*}"
    local rest="${line#*:}"
    # Canonicalize path and convert to /memories/...
    local canon; canon="$(cd "$(dirname -- "$path")" 2>/dev/null && pwd -P)/$(basename -- "$path")" || continue
    case "$canon" in
      "$real_root"/*) : ;;
      *) continue ;;
    esac
    local vp="/memories${canon#$real_root}"
    local scope; scope="$(scope_of "$vp")"
    [[ "$(acl_check "$scope" read)" == "allow" ]] || continue
    match_out+="${vp}:${rest}"$'\n'
    hits=$((hits + 1))
    (( hits >= limit )) && break
  done <<< "$raw_matches"
  if (( hits == 0 )); then
    echo "No matches for query in $( [[ -n "$scope_filter" ]] && echo "/memories/$scope_filter" || echo "/memories" )."
    audit "search" "/memories${scope_filter:+/$scope_filter}" 0 acl_filtered
    return 0
  fi
  printf '%s' "$match_out"
  audit "search" "/memories${scope_filter:+/$scope_filter}" "$hits" ok
}

cmd_ttl_sweep() {
  # Precondition:  registry exists and has scopes with non-null ttl_days.
  # Postcondition: every file whose mtime is older than its scope's ttl_days
  #                has been deleted (or printed in dry-run mode); one audit line
  #                written per deletion; one sync job enqueued per deletion.
  #                Running twice in a row is safe (re-entrant: already-deleted
  #                files are simply absent on the second pass).
  local dry_run=0
  while (( $# )); do
    case "$1" in
      --dry-run) dry_run=1; shift ;;
      *) shift ;;
    esac
  done

  if [[ ! -f "$MEMORY_REGISTRY" ]]; then
    echo "TTL sweep: 0 files expired across 0 scopes (no registry)"
    return 0
  fi

  # Build list of (scope ttl_days) pairs where ttl_days is not null.
  local scope_ttl_pairs
  scope_ttl_pairs=$(python3 - "$MEMORY_REGISTRY" <<'PY'
import json, sys
with open(sys.argv[1]) as f:
    reg = json.load(f)
scopes = reg.get("scopes", {})
defaults = reg.get("defaults", {})
# Emit "scope ttl_days" lines for scopes with non-null ttl.
for name, entry in scopes.items():
    ttl = entry.get("ttl_days")
    if ttl is not None:
        print(f"{name} {int(ttl)}")
# Also handle the defaults block if it has a ttl and scopes inherit it —
# but only for scopes that don't have an explicit ttl key.
default_ttl = defaults.get("ttl_days")
if default_ttl is not None:
    # Scopes already emitted are explicitly listed; skip them for defaults.
    explicit = set(scopes.keys())
    # Scan MEMORY_ROOT for directories that are not in explicit scopes.
    import os, sys
    mem_root = os.environ.get("MEMORY_ROOT", os.path.expanduser("~/.claude/memories"))
    for d in os.scandir(mem_root):
        if d.is_dir() and not d.name.startswith(".") and d.name not in explicit:
            print(f"{d.name} {int(default_ttl)}")
PY
)

  local total_files=0 total_scopes=0
  local now; now=$(date +%s)

  while IFS=' ' read -r scope ttl_days; do
    [[ -z "$scope" || -z "$ttl_days" ]] && continue
    local scope_dir="$MEMORY_ROOT/$scope"
    [[ -d "$scope_dir" ]] || continue

    # Precondition for ACL: TTL sweep is a system operation — run as _system.
    # We bypass ACL here intentionally (TTL is a governance enforcement, not
    # a data operation). JUSTIFICATION: TTL enforcement is defined in the
    # registry by the curator; enforcing it must not be blocked by ACL.
    # source: memory/contract.md §6 (over-cap behavior must not fail silently)

    local cutoff=$(( now - ttl_days * 86400 ))
    local scope_deleted=0

    _sweep_scope() {
      while IFS= read -r fpath; do
        [[ -z "$fpath" ]] && continue
        [[ -f "$fpath" ]] || continue
        local fmtime
        fmtime=$(python3 -c "import os; print(int(os.path.getmtime('$fpath')))" 2>/dev/null || echo 0)
        if (( fmtime < cutoff )); then
          local vp="/memories/$scope/${fpath#$scope_dir/}"
          if (( dry_run )); then
            echo "[dry-run] would expire: $vp (mtime $(date -r "$fmtime" -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo $fmtime))"
          else
            rm -f -- "$fpath"
            audit "ttl_expire" "$vp" 0 ok
            enqueue_sync "delete" "$vp" "$scope"
          fi
          scope_deleted=$(( scope_deleted + 1 ))
        fi
      done < <(find "$scope_dir" -type f ! -name '.*' 2>/dev/null)
    }

    if (( dry_run )); then
      _sweep_scope
    else
      with_lock "$scope" _sweep_scope
    fi

    if (( scope_deleted > 0 )); then
      total_scopes=$(( total_scopes + 1 ))
      total_files=$(( total_files + scope_deleted ))
    fi
  done <<< "$scope_ttl_pairs"

  if (( dry_run )); then
    echo "[dry-run] TTL sweep: $total_files files would expire across $total_scopes scopes"
  else
    echo "TTL sweep: $total_files files expired across $total_scopes scopes"
  fi
}

cmd_audit() {
  # Precondition:  AUDIT_LOG exists (may be absent if no writes have occurred).
  # Postcondition: prints lines from the last 24 hours (or --since window),
  #                followed by a summary block and anomaly flags.
  local since_iso=""
  while (( $# )); do
    case "$1" in
      --since) since_iso="$2"; shift 2 ;;
      *) shift ;;
    esac
  done

  if [[ ! -f "$AUDIT_LOG" ]]; then
    echo "Audit log is empty — no writes recorded yet."
    return 0
  fi

  # Determine cutoff epoch second.
  local cutoff_epoch
  if [[ -n "$since_iso" ]]; then
    cutoff_epoch=$(python3 -c "
from datetime import datetime, timezone
s = '$since_iso'
# Accept formats: YYYY-MM-DDTHH:MM:SSZ, YYYY-MM-DD, YYYY-MM-DDTHH:MM:SS+00:00
for fmt in ('%Y-%m-%dT%H:%M:%SZ','%Y-%m-%d','%Y-%m-%dT%H:%M:%S+00:00','%Y-%m-%dT%H:%M:%S'):
    try:
        dt = datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        print(int(dt.timestamp()))
        break
    except ValueError:
        pass
else:
    import sys; print('error', file=sys.stderr); sys.exit(1)
" 2>/dev/null) || { echo "Error: invalid --since value: $since_iso"; exit 1; }
  else
    cutoff_epoch=$(( $(date +%s) - 86400 ))
  fi

  python3 - "$AUDIT_LOG" "$cutoff_epoch" <<'PY'
import sys, collections, datetime

log_path = sys.argv[1]
cutoff = int(sys.argv[2])

lines = []
with open(log_path) as f:
    for raw in f:
        raw = raw.rstrip('\n')
        if not raw:
            continue
        parts = raw.split('\t')
        if len(parts) < 8:
            continue
        ts_str, agent, scope, cmd, vpath, bytes_s, sha, result = parts[:8]
        try:
            dt = datetime.datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%SZ")
            dt = dt.replace(tzinfo=datetime.timezone.utc)
            epoch = int(dt.timestamp())
        except ValueError:
            continue
        if epoch < cutoff:
            continue
        lines.append({
            "ts": ts_str, "epoch": epoch, "agent": agent, "scope": scope,
            "cmd": cmd, "vpath": vpath, "bytes": int(bytes_s or 0),
            "sha": sha, "result": result
        })

if not lines:
    print("No audit entries in the requested window.")
    sys.exit(0)

# ── raw log ──────────────────────────────────────────────────────────────────
print(f"=== Audit log ({len(lines)} entries) ===")
for e in lines:
    print(f"  {e['ts']}  {e['agent']:20s}  {e['scope']:15s}  {e['cmd']:12s}  {e['result']:12s}  {e['vpath']}")

# ── summary ──────────────────────────────────────────────────────────────────
total_writes = sum(1 for e in lines if e['cmd'] not in ('view','search','scopes','preamble','sync-status'))
acl_denials  = [e for e in lines if e['result'] == 'acl_denied']
by_agent_bytes = collections.Counter()
for e in lines:
    by_agent_bytes[e['agent']] += e['bytes']

# scope max_file_kb from registry (best effort)
try:
    import json, os
    reg_path = os.environ.get('MEMORY_REGISTRY', '')
    scope_max = {}
    if reg_path and os.path.isfile(reg_path):
        with open(reg_path) as f:
            reg = json.load(f)
        defaults_kb = reg.get('defaults', {}).get('max_file_kb', 100)
        for sname, sentry in reg.get('scopes', {}).items():
            scope_max[sname] = sentry.get('max_file_kb', defaults_kb)
    mem_root = os.environ.get('MEMORY_ROOT', os.path.expanduser('~/.claude/memories'))
    scope_near_limit = []
    for sname, max_kb in scope_max.items():
        scope_dir = os.path.join(mem_root, sname)
        if not os.path.isdir(scope_dir):
            continue
        for fname in os.listdir(scope_dir):
            fpath = os.path.join(scope_dir, fname)
            if os.path.isfile(fpath):
                kb = os.path.getsize(fpath) / 1024
                if kb >= max_kb * 0.9:
                    scope_near_limit.append((sname, fname, kb, max_kb))
except Exception:
    scope_near_limit = []

print()
print("=== Summary ===")
print(f"  Total writes in window : {total_writes}")
print(f"  ACL denials            : {len(acl_denials)}")
if acl_denials:
    denial_by = collections.Counter((e['agent'], e['scope']) for e in acl_denials)
    for (ag, sc), cnt in denial_by.most_common():
        print(f"    agent={ag} scope={sc} : {cnt}")
print()
print("  Top 5 agents by byte volume:")
for ag, bts in by_agent_bytes.most_common(5):
    print(f"    {ag:30s}  {bts:>10d} bytes")
if scope_near_limit:
    print()
    print("  Files within 10% of max_file_kb:")
    for sname, fname, kb, max_kb in scope_near_limit:
        print(f"    /memories/{sname}/{fname}  {kb:.1f}KB / {max_kb}KB limit")

# ── anomalies ────────────────────────────────────────────────────────────────
anomalies = []

# >50 writes in any rolling hour, per scope
bucket = collections.defaultdict(list)
for e in lines:
    if e['cmd'] not in ('view','search','scopes','preamble','sync-status'):
        bucket[e['scope']].append(e['epoch'])
for scope, epochs in bucket.items():
    epochs.sort()
    for i, ep in enumerate(epochs):
        window = [t for t in epochs[i:] if t - ep <= 3600]
        if len(window) > 50:
            anomalies.append(f"  [ANOMALY] scope '{scope}': {len(window)} writes in 1-hour window starting {datetime.datetime.utcfromtimestamp(ep).strftime('%H:%M:%SZ')}")
            break

# agent writing to >3 different scopes
agent_scopes = collections.defaultdict(set)
for e in lines:
    if e['cmd'] not in ('view','search','scopes','preamble','sync-status'):
        agent_scopes[e['agent']].add(e['scope'])
for ag, scopes in agent_scopes.items():
    if len(scopes) > 3:
        anomalies.append(f"  [ANOMALY] agent '{ag}' wrote to {len(scopes)} scopes: {sorted(scopes)}")

# >= 5 consecutive acl_denied from same agent
agent_denial_run = collections.defaultdict(int)
last_agent_result = {}
for e in sorted(lines, key=lambda x: x['epoch']):
    key = e['agent']
    if e['result'] == 'acl_denied':
        agent_denial_run[key] += 1
        if agent_denial_run[key] == 5:
            anomalies.append(f"  [ANOMALY] agent '{key}' has {agent_denial_run[key]} consecutive acl_denied (possible poisoning attempt)")
    else:
        agent_denial_run[key] = 0

if anomalies:
    print()
    print("=== Anomalies ===")
    for a in anomalies:
        print(a)
else:
    print()
    print("  No anomalies detected.")
PY
}

cmd_rename() {
  local old_vpath="$1" new_vpath="$2"
  local old_real new_real
  resolve_path "$old_vpath" old_real || exit 1
  resolve_path "$new_vpath" new_real || exit 1
  local old_scope new_scope
  old_scope="$(scope_of "$old_vpath")"
  new_scope="$(scope_of "$new_vpath")"
  if [[ "$(acl_check "$old_scope" write)" == "deny" ]]; then
    acl_deny "$old_scope" write
    audit "rename" "$old_vpath" 0 acl_denied
    exit 1
  fi
  if [[ "$(acl_check "$new_scope" write)" == "deny" ]]; then
    acl_deny "$new_scope" write
    audit "rename" "$new_vpath" 0 acl_denied
    exit 1
  fi
  ensure_parent "$new_real"
  local scope="$old_scope"
  _do_rename() {
    if [[ ! -e "$old_real" ]]; then
      echo "Error: The path $old_vpath does not exist"
      audit "rename" "$old_vpath" 0 missing
      exit 1
    fi
    if [[ -e "$new_real" ]]; then
      echo "Error: The destination $new_vpath already exists"
      audit "rename" "$new_vpath" 0 duplicate
      exit 1
    fi
    mv -- "$old_real" "$new_real"
    audit "rename" "$old_vpath->$new_vpath" 0 ok
    enqueue_sync "rename" "$old_vpath" "$new_scope" "$new_vpath"
    echo "Successfully renamed $old_vpath to $new_vpath"
  }
  with_lock "$scope" _do_rename
}

# ─── dispatch ────────────────────────────────────────────────────────────────

mkdir -p "$MEMORY_ROOT" "$LOCK_DIR"

cmd="${1:-}"; shift || true
case "$cmd" in
  view)        cmd_view        "${1:?path}" "${2:-}" "${3:-}" ;;
  create)      cmd_create      "${1:?path}" "${2:?file_text}" ;;
  str_replace) cmd_str_replace "${1:?path}" "${2:?old_str}" "${3:?new_str}" ;;
  insert)      cmd_insert      "${1:?path}" "${2:?insert_line}" "${3:?insert_text}" ;;
  delete)      cmd_delete      "${1:?path}" ;;
  rename)      cmd_rename      "${1:?old_path}" "${2:?new_path}" ;;
  search)      cmd_search      "$@" ;;
  scopes)      cmd_scopes ;;
  preamble)    cmd_preamble ;;
  sync-status) cmd_sync_status ;;
  drain-sync)  cmd_drain_sync "$@" ;;
  commit-sync) cmd_commit_sync "${1:?job_id}" ;;
  release-sync) cmd_release_sync "${1:?job_id}" ;;
  ttl-sweep)   cmd_ttl_sweep   "$@" ;;
  audit)       cmd_audit       "$@" ;;
  -h|--help|"") grep -E '^#( |$)' "$0" | sed 's/^# \{0,1\}//' ;;
  *) die "unknown command: $cmd (expected: view|create|str_replace|insert|delete|rename|search|scopes|preamble|sync-status|drain-sync|commit-sync|release-sync|ttl-sweep|audit)" ;;
esac
