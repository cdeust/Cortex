#!/usr/bin/env python3
"""
pii-daemon.py — Persistent PII-scan server for memory-tool.sh §7.2

Architecture decision (profile-driven):
  Profiling on 2026-04-24 showed interpreter cold-start = 37.1 ms on macOS,
  while scan logic (json_load + compile + scan_loop) = 1.3 ms.  The 37 ms
  cold-start exceeds the 50 ms write-path target when combined with other
  per-write overheads.  A persistent daemon eliminates cold-start entirely:
  after the first request the amortised cost per scan is ~1 ms (socket I/O
  + scan loop).  Option B (bash grep port) was rejected because it cannot
  reproduce the Shannon-entropy cross-check.  Option D (threshold skip) was
  rejected because the 3% optimisation target is interpreter startup, not
  content-size skipping.
  Source for timing: memory/pii-profile.md

Protocol (newline-delimited over AF_UNIX stream socket):
  Client → daemon: one JSON object followed by newline.
    { "content": "<utf8 text>", "strict": <bool> }
  Daemon → client: one JSON object followed by newline.
    { "result": "pass" | "blocked:<rule_id>" | "pii_scan_error" }
  Framing invariant: exactly one response line per request line.

Lifecycle:
  - Started on-demand by memory-tool.sh when socket absent or stale.
  - Accepts connections until IDLE_TIMEOUT seconds pass with no request.
  - SIGTERM / SIGINT: flush + remove socket + exit cleanly.
  - Stale socket cleanup: daemon writes its PID into a sidecar .pid file;
    the shell launcher checks the PID before deciding to restart.

Correctness invariants (identical to pii-scanner.py §7.2 contract):
  - Matched bytes NEVER written to any output — only rule IDs.
  - MEMORY_PII_SCAN_DISABLE=1 → result "pii_scan_disabled" (checked at
    request time so live env-var changes take effect without daemon restart).
  - MEMORY_PII_STRICT=1 → include low-confidence rules (email, phone).
  - Scanner errors → result "pii_scan_error" (caller allows write).
  - Rules are compiled once at daemon start; JSON re-read if rules file
    mtime changes (hot-reload without restart).

Complexity analysis:
  Per-request scan: O(R × N) where R = number of enabled rules (≤14) and
  N = input length in characters.  re.search on CPython uses a DFA/NFA
  hybrid; worst-case is O(R × N) but average on benign text is sub-linear
  because most patterns anchor on rare byte sequences.  The entropy check
  is O(M) where M = length of matched group (bounded by pattern).
  Total per-request: O(14N) ≈ O(N).  At N = 10 KB this is ~140 K steps —
  well within 1 ms on modern hardware (confirmed by profiling above).
"""

import sys
import os
import re
import json
import math
import socket
import signal
import threading
import time
import pathlib

# ── constants ─────────────────────────────────────────────────────────────────

IDLE_TIMEOUT = 30.0  # seconds without any request before self-shutdown
BACKLOG = 8  # max pending connections in accept queue
MAX_MSG_BYTES = 2 * 1024 * 1024  # 2 MB hard cap per request (DoS guard)

# ── state (module-level, daemon is single-process single-threaded) ─────────────

_rules_path: str = ""
_rules_mtime: float = 0.0
_entropy_thresh: float = 3.5
_compiled_high: list = []  # (pattern, rule_dict) for confidence != low
_compiled_all: list = []  # all rules, including low-confidence


def _load_rules(path: str) -> None:
    """
    Load and compile all rules from the JSON file at *path*.

    WHY compile at load time rather than per-request:
    re.compile() on CPython caches up to 512 patterns internally, but the
    cache is keyed by (pattern, flags) — redundant recompilation still burns
    ~0.1 ms per call.  Explicit pre-compilation removes that cost and makes
    the hot path a pure re.search over already-compiled objects.

    CORRECTNESS: if the rules file is modified while the daemon is running
    (hot-reload), the caller detects the mtime change and calls this function
    again.  The two lists (_compiled_high, _compiled_all) are replaced
    atomically from the caller's perspective (single-threaded event loop).
    """
    global _rules_mtime, _entropy_thresh, _compiled_high, _compiled_all

    with open(path) as f:
        cfg = json.load(f)

    _entropy_thresh = cfg.get("_entropy_threshold", {}).get("value", 3.5)
    rules = cfg.get("rules", [])

    high: list = []
    all_rules: list = []
    for rule in rules:
        try:
            pat = re.compile(rule["pattern"])
        except re.error:
            continue  # skip malformed rules; don't crash the daemon
        entry = (pat, rule)
        all_rules.append(entry)
        if rule.get("confidence", "high") != "low":
            high.append(entry)

    _compiled_high = high
    _compiled_all = all_rules
    _rules_mtime = pathlib.Path(path).stat().st_mtime


def _maybe_reload(path: str) -> None:
    """Re-load rules if the file has been modified since last load."""
    try:
        mtime = pathlib.Path(path).stat().st_mtime
        if mtime != _rules_mtime:
            _load_rules(path)
    except OSError:
        pass  # rules file temporarily unavailable — keep using compiled set


def _shannon_entropy(s: str) -> float:
    """
    Shannon entropy H = -∑ p_i log₂ p_i over character histogram.

    Source: Shannon, C.E. (1948). 'A Mathematical Theory of Communication.'
    Bell System Technical Journal 27(3), 379-423.
    Threshold 3.5 bits/char: TruffleHog v2 design doc (Cornwell, T., 2019).

    Complexity: O(M) where M = len(s).  Called only when entropy_check=true
    on a matched group — never on the full input.
    """
    if not s:
        return 0.0
    freq: dict[str, int] = {}
    for c in s:
        freq[c] = freq.get(c, 0) + 1
    n = len(s)
    return -sum((v / n) * math.log2(v / n) for v in freq.values())


def _scan(content: str, strict: bool) -> str:
    """
    Scan *content* against the compiled rule set.

    Returns: "pass" | "blocked:<rule_id>" | "pii_scan_error"

    INVARIANT: the matched bytes are NEVER included in the return value —
    only the rule ID string from pii-rules.json is returned.

    WHY strict parameter here (not only at daemon start):
    Strict mode is an environment variable that can change between writes
    (e.g., an operator enables it for a sensitive session without restarting
    the daemon).  Checking it per-request preserves the contract.
    """
    rules = _compiled_all if strict else _compiled_high
    for pat, rule in rules:
        try:
            m = pat.search(content)
        except re.error:
            continue
        if m is None:
            continue
        if rule.get("entropy_check"):
            matched_str = m.group(1) if m.lastindex and m.lastindex >= 1 else m.group(0)
            if _shannon_entropy(matched_str) <= _entropy_thresh:
                continue  # placeholder string (low entropy); pass through
        # Confirmed match — return rule ID only, never the matched text.
        return f"blocked:{rule['id']}"
    return "pass"


def _handle_request(raw: bytes) -> str:
    """
    Parse one request frame, apply environment toggles, dispatch to _scan.

    WHY environment toggles are checked per-request, not at daemon start:
    MEMORY_PII_SCAN_DISABLE and MEMORY_PII_STRICT are designed to be set
    by the operator without restarting the daemon (e.g., in test scaffolding).
    Checking os.environ at request time preserves the contract from
    pii-scanner.py's original design.
    """
    if os.environ.get("MEMORY_PII_SCAN_DISABLE"):
        return "pii_scan_disabled"

    try:
        req = json.loads(raw.decode("utf-8", errors="replace"))
        content = req["content"]
        strict = bool(req.get("strict", False)) or (
            os.environ.get("MEMORY_PII_STRICT", "") == "1"
        )
    except Exception:
        return "pii_scan_error"

    try:
        _maybe_reload(_rules_path)
        return _scan(content, strict)
    except Exception:
        return "pii_scan_error"


# ── server loop ───────────────────────────────────────────────────────────────


def _serve(sock_path: str) -> None:
    """
    Accept-loop: one connection → one request → one response → close.

    WHY one-shot connections rather than persistent per-client connections:
    The caller (memory-tool.sh) is a short-lived bash process.  Persistent
    connections would require the shell to hold an open file descriptor
    across tool invocations, which bash cannot do reliably across subshell
    boundaries.  One-shot is simpler and the per-connection overhead is
    ~0.1 ms (socket accept + read + write on loopback AF_UNIX).

    Idle timeout: the daemon exits after IDLE_TIMEOUT seconds with no
    accepted connection.  This prevents zombie daemons accumulating on a
    developer workstation.
    """
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        os.unlink(sock_path)
    except FileNotFoundError:
        pass

    server.bind(sock_path)
    server.listen(BACKLOG)
    server.settimeout(IDLE_TIMEOUT)

    while True:
        try:
            conn, _ = server.accept()
        except socket.timeout:
            # No request for IDLE_TIMEOUT seconds → clean shutdown.
            break
        except OSError:
            break

        try:
            # Read until newline (framing delimiter).
            buf = b""
            while b"\n" not in buf:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                buf += chunk
                if len(buf) > MAX_MSG_BYTES:
                    break  # DoS guard: drop oversized request

            result = _handle_request(buf.rstrip(b"\n"))
            conn.sendall((result + "\n").encode("utf-8"))
        except Exception:
            try:
                conn.sendall(b"pii_scan_error\n")
            except Exception:
                pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    server.close()


def _cleanup(sock_path: str, pid_path: str) -> None:
    for p in (sock_path, pid_path):
        try:
            os.unlink(p)
        except FileNotFoundError:
            pass


def main() -> None:
    if len(sys.argv) < 3:
        sys.stderr.write("usage: pii-daemon.py <rules_json> <sock_path>\n")
        sys.exit(1)

    global _rules_path
    _rules_path = sys.argv[1]
    sock_path = sys.argv[2]
    pid_path = sock_path + ".pid"

    try:
        _load_rules(_rules_path)
    except Exception as exc:
        sys.stderr.write(f"pii-daemon: failed to load rules: {exc}\n")
        sys.exit(1)

    # Write PID sidecar so the shell launcher can verify we are still alive.
    pathlib.Path(pid_path).write_text(str(os.getpid()))

    # Clean shutdown on SIGTERM / SIGINT.
    def _sighandler(signum, frame):
        _cleanup(sock_path, pid_path)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _sighandler)
    signal.signal(signal.SIGINT, _sighandler)

    try:
        _serve(sock_path)
    finally:
        _cleanup(sock_path, pid_path)


if __name__ == "__main__":
    main()
