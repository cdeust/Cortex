# Resident auto-capture worker (W3-1c)

Status: implementation contract, before code; runtime/energy measurements pending.
Base: `d72e8b83`. No production data is used by development tests.
Runtime prerequisite: W2-1a's `close_shared_store_on_exit` implementation, which
looks only in `sys.modules` and never imports a store during idle teardown.

The hook retains filtering, secret scrubbing, gist/artifact creation and the exact
`remember` payload. It sends that payload to one resident process per resolved
`CORTEX_CLAUDE_DIR` (the existing default remains `~/.claude`). Only the worker
imports the handler. Its persistent event loop preserves the handler's existing
store singleton and embedding-engine singleton between requests.

## Lifecycle and admission

A private `.capture-worker/` directory holds a Unix stream socket (0600), an
exclusive lifetime `flock` and a short launch lock. The creator binds/listens
before spawning, then passes listener and lease descriptors to the child using
`Popen(pass_fds=..., start_new_session=True)`. The launch lock is not inherited.
Every connection inspects the socket under this lock: bind creates the pathname
before chmod sets its 0600 mode, so even a warm client must wait for publication.
Sending and admission happen after releasing the launch lock. A dead worker
releases its lease in the kernel; its stale socket is removed only while holding
that lease. A live lease with an unusable socket is an explicit failure, never
permission to launch a second worker.

`GroomerCoordinator` supplies the per-resource lock pattern, **not** an idle TTL:
it schedules consolidation periods and tracks sessions. The duration comes from
the existing `MCPClient` default `idleTimeoutMs=300000` (300 seconds), exposed here
as `CORTEX_CAPTURE_IDLE_SECONDS`. Invalid/nonpositive values fail explicitly.
Idle time starts after the last completed request; neither queued nor active
work expires. Exit closes the lease and removes only the worker's own socket.
Before releasing that lease, `close_shared_store_on_exit` closes every loaded
shared store on normal expiry or error (the existing issue #398 lifecycle rule).
An idle worker that never received a payload does not import a store to close it.

Reception is independent of inference. One running request and one pending
mailbox bound application memory: capacity one is the rendezvous structure, not
an empirically tuned throughput threshold. A full mailbox waits for a place
within the transport deadline; only expiration rejects admission. Ordinary bursts
therefore wait for progress without losing work while within that budget.
The ACK means admitted in volatile memory, **not** persisted. Crash after ACK may
lose accepted work. There is no automatic replay after uncertain delivery, which
could duplicate a write. Durable delivery is outside this change.

Absent/refused socket triggers one launch attempt. Spawn, transport, malformed
frame and admission-deadline failures produce a diagnostic and a
`capture_skipped` telemetry sample; a failed worker never falls back into the hook.
Dispatch, receive and processing errors report their measured monotonic duration.
Listener/cleanup failures use a distinct `capture_worker_lifecycle` sample with
their own measured duration. Neither event is recorded as `remember`, so these
diagnostics do not enter the handler's `remember` latency series.
Worker handler failure has the same observable error boundary. A platform the worker
cannot run on (Windows: CPython has no `AF_UNIX`, no `fcntl`, no `geteuid`, and
`Popen` has no `pass_fds`) is decided by the capability test
`capture_peer.is_supported()`, before any I/O, not by catching an error. There the
hook never loads the handler: importing `sentence_transformers` alone measured
3.61 s on 2026-10-07 (macOS, isolated SQLite store, `torch` 0.72 s, warm), against a
hook `timeout` of 10 s. It validates the payload, writes it atomically to
`.capture-worker/spool/<time>-<pid>-<id>.json` and starts `capture_drain` detached
(`capture_dispatch.popen_options`: `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP` on
Windows, `start_new_session` elsewhere, no inherited descriptors; stderr to
`drain.err`), without waiting.
The drainer takes a non-blocking kernel lock (`msvcrt.locking` / `flock`); a drainer
that loses it exits, the winner stores every pending file through the same
`capture_store.store` the worker awaits (one model load per burst), deletes each file
only after it was stored, releases the lock and scans once more, so a file written
during the release is never stranded. Delivery is at-least-once; a replay is absorbed
by the write gate. A refused or failing file is renamed `*.rejected` and reported as
`capture_skipped`. No TCP, abstract-socket or named-pipe transport is built: the spool
needs none, and a named pipe with a current-user DACL would add a second transport,
lease and spawn implementation (issue #659, ADR-1094). `ci.yml`'s Windows leg runs the
capture test files, so the native Windows behaviour is exercised there.

## Protocol and trust boundary

Each connection carries one four-byte network-order length and one UTF-8 JSON
object, followed by a one-byte admission result. The frame limit reuses
`shared.content_hardening.CONTENT_MAX_BYTES` (1 MiB), applied to the complete
serialized object's content. Its complete JSON envelope is calculated with the
existing remember directory/tag limits, exact fixed fields, and JSON's worst
six-byte escaping of a one-byte control (RFC 8259 §7). Boundary tests cover full
content plus metadata and Unicode/control escaping. An oversized frame is
rejected before allocation, never truncated. Content above the existing 1 MiB
hardening envelope or references beyond the existing remember schema limits are
refused explicitly. The 10-second
transport hang guard comes from the existing hook timeout in F1/W3-1.

The directory is 0700; owner is the effective current user. Symlinks in any path
component, wrong owners and unsafe writable parents are rejected. Root-owned
sticky temporary directories are allowed as ancestors for isolated tests.
Socket type, owner and exact 0600 mode are checked before connecting. Both peers
check kernel credentials: Linux `SO_PEERCRED`, macOS `getpeereid`. Same-UID
processes are inside this boundary; it does not protect against compromised code
running as the owner. Overlong Unix paths fail explicitly rather than redirecting
to a shared temporary directory.

## Verification and sources

Fixtures cover first spawn/reuse, concurrent launches, idle exit, crash/relaunch,
bounded admission during blocked inference, unchanged payload, malformed/oversize
frames, unsafe modes/owners/symlinks, foreign credentials and explicit failures.
Tests inject the handler and use temporary directories only. Acceptance CPU/RSS,
warm encode and remember latency measurements remain owner/CI work.

The bind/chmod regression test holds publication with events and starts a second
client before chmod. This reproduces CI's premature permission failure without
relaxing the 0600 check. Deadline tests run on Python 3.10 as well: its
`concurrent.futures.TimeoutError` is distinct from builtin `TimeoutError`.
Both timeout sources must cancel the pending lock acquisition.

The child detaches all three stdio streams; it cannot retain a hook output pipe.
Its Python diagnostics use a private rotating file, sized from F9's measured
196 kB/day × 30 days, retaining one previous segment. Skip telemetry uses the
existing telemetry sink and honors its opt-out setting.

Primary references:

- `mcp_server/infrastructure/groomer_coordinator.py` and `_io.py`: lock/lifetime pattern.
- `mcp_server/infrastructure/mcp_client.py`: default idle duration.
- `mcp_server/shared/content_hardening.py`: existing content-byte envelope.
- `mcp_server/handlers/remember.py:_get_store` and embedding engine: persistent instances.
- The worker reuses `post_tool_capture._load_remember`, the existing deferred
  composition loader. Its existing hooks→handlers baseline debt is retained;
  infrastructure gains no handler import and no new layer exemption is added.
- [RFC 8259 §7](https://www.rfc-editor.org/rfc/rfc8259#section-7): worst-case JSON escaping.
- [Python Future](https://docs.python.org/3/library/concurrent.futures.html#concurrent.futures.Future): cancellation of the non-polling launch-lock waiter.
- [Python Future TimeoutError](https://docs.python.org/3/library/concurrent.futures.html#concurrent.futures.TimeoutError): builtin alias only since Python 3.11.
- [Python socket](https://docs.python.org/3/library/socket.html): streams, timeout, socket APIs.
- [Python subprocess](https://docs.python.org/3/library/subprocess.html#popen-constructor): FD inheritance and detached child.
- [Linux unix(7)](https://man7.org/linux/man-pages/man7/unix.7.html): path permissions, credential validation; socket mode alone is not portable authorization.
- [Apple getpeereid(3)](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man3/getpeereid.3.html): kernel peer effective UID.
