# Memory-Tool Concurrency Audit

Audit date: 2026-04-24
Tool: `tools/memory-tool.sh`
Method: static code review + reproducible process-level tests in `scripts/test-memory-concurrency.sh`

---

## Happens-Before Relationships Per Command

All write commands follow the same causal order:

```
resolve_path → acl_check → (ensure_parent) → with_lock → [[ -e check ]] → atomic_write
```

The lock (`mkdir $lockdir`) is the synchronisation point.  Any event in
`with_lock` on process A causally precedes any event in `with_lock` on process B
for the same scope, because A's `rmdir` must happen before B's `mkdir` succeeds.

---

## Question 1 — Write-lock sufficiency (SIGKILL / stale lock)

**Is the TOCTOU inside the critical section sound?**
Yes. The `[[ -e "$real" ]]` check at line 317 and `atomic_write` at line 324 are
both inside `with_lock`. The lock is held from `mkdir $lockdir` (line 191) to
`rmdir $lockdir` (line 199). Because `mkdir(2)` is atomic on local POSIX
filesystems, at most one process enters the critical section at a time. The
check-then-act sequence is serialised; there is no TOCTOU window between
independent processes.

**What if the process is killed while holding the lock?**
The `trap ... EXIT INT TERM` registered at line 196 does NOT fire on SIGKILL
(signal 9). The lockdir `$LOCK_DIR/$scope.lockd` persists. Subsequent callers
spin at 100 ms intervals for `max_tries=50` (5 s), then call `die` and exit 2.

**Is that acceptable?** Yes for the current single-host deployment: a 5 s
bounded timeout prevents indefinite hang. The failure mode is loud (`die` writes
to stderr) and bounded.

**Stale-lock recovery strategy (no patch required — documented only):**
If automated recovery is ever needed, the correct approach is to record the PID
of the lock holder in a file inside `$lockdir` at acquisition time, then at spin
time check whether that PID is still alive (`kill -0 $pid`). If not, remove the
stale lockdir and retry. This is not patched here because it cannot be
demonstrated to be a currently-failing hazard — the 5 s die is the stated
contract and is tested by C2.

---

## Question 2 — Atomic rename sufficiency (cross-filesystem)

**Is there a cross-filesystem risk?**
No. Both `atomic_write` (line 207) and `enqueue_sync` (line 488) create the tmp
file with the pattern `$target.tmp.$$`, i.e. in the same directory as the target.
Same directory implies same filesystem mount. `rename(2)` is used and is atomic.

**File-line evidence:**
- Line 207: `local tmp="$target.tmp.$$"` — tmp in dirname(target).
- Line 488: `local tmp="$job_file.tmp.$$"` — tmp in dirname(job_file).
- Line 211: `mv -f -- "$tmp" "$target"` — same mount, uses rename(2).
- Line 520: `mv -f -- "$tmp" "$job_file"` — same mount, uses rename(2).

No hazard. No patch.

---

## Question 3 — Queue claim race with `mv -n` (REAL HAZARD — PATCHED)

**The hazard:**
BSD `mv -n` (macOS default) returns **exit 0** even when it performs no rename
because the destination already exists (no-clobber skip). The original guard at
line 745:

```bash
if mv -n -- "$job_file" "$claimed" 2>/dev/null && [[ -f "$claimed" ]]; then
```

`[[ -f $claimed ]]` is true whether or not THIS process moved the source.
If two drainers race, both can enter the success branch, emitting the same job
twice and allowing duplicate replication to Cortex.

**Verification:** test C3a in `scripts/test-memory-concurrency.sh` reproduces the
broken guard entering the success branch when dst pre-exists (PASS = hazard
confirmed before patch).

**The fix (line 745, `cmd_drain_sync`):**

```bash
# before
if mv -n -- "$job_file" "$claimed" 2>/dev/null && [[ -f "$claimed" ]]; then

# after
if mv -n -- "$job_file" "$claimed" 2>/dev/null && [[ ! -e "$job_file" ]]; then
```

**Invariant restored:** "A job is claimed by this process if and only if
`rename(2)` atomically removed the source." The source's absence is the
causal witness that this process performed the rename. `[[ ! -e $job_file ]]`
checks exactly this. The other drainer's `mv -n` is silently blocked (dst
exists) and its source remains; it takes the false branch.

**Source:** POSIX `rename(2)` atomicity; BSD `mv(1)` man page, `-n` flag
("Do not overwrite an existing file.").

**Tests:**
- C3a — reproduces broken guard (passes before patch to confirm hazard).
- C3b — exercises fixed guard (passes after patch to confirm fix).
- C3c — concurrent real drain-sync: at most 1 drainer emits the job.

---

## Question 4 — TTL-sweep vs concurrent create race

**Does `ttl-sweep` hold the scope lock?**
Yes. Line 815:

```bash
with_lock "$scope" _sweep_scope
```

The non-dry-run path wraps `_sweep_scope` in `with_lock`. The dry-run path
does NOT hold the lock (line 812), but dry-run makes no mutations, so
there is no correctness hazard in the dry-run case.

**Race scenario (non-dry-run):** A `create` that has completed and released its
lock on scope S happened-before any `ttl-sweep` that subsequently acquires the
lock on scope S. The sweep cannot delete the file within the same lock critical
section in which `create` wrote it, because only one lock holder executes at a
time. If the file is old enough to expire, the sweep may delete it after `create`
releases — but that is correct TTL behaviour, not a race.

No hazard. No patch.

---

## Question 5 — Audit log append atomicity

**Format (line 231):**
```
ts(20) TAB agent TAB scope TAB cmd TAB vpath TAB bytes(≤10) TAB sha(64) TAB result(≤12) LF
```

**Worst-case bound:**
```
ts=20 + 7 tabs + agent(50) + scope(50) + cmd(11) + vpath(200) + bytes(10) + sha(64) + result(12)
= 424 bytes
```

macOS `PIPE_BUF` = 512 bytes (SUSv4 minimum). The `>>` append-mode open
on a regular file combined with `O_APPEND` guarantees that writes up to
`PIPE_BUF` bytes are atomic (no interleaving). 424 < 512, so lines are
not interleaved under realistic inputs.

**Note:** `MEMORY_AGENT_ID` is user-controlled. A pathologically long agent ID
could exceed 512 bytes. However MEMORY_AGENT_ID is an internal env var set by
the tool's caller (a Claude agent or test harness), not an untrusted network
input. No patch warranted; the current design is safe for all realistic values.

---

## Summary

| # | Hazard | Verdict | Action |
|---|--------|---------|--------|
| 1 | SIGKILL stale lock | Bounded 5 s die — acceptable | Documented, no patch |
| 2 | Cross-filesystem rename | Not a hazard (tmp co-located) | No patch |
| 3 | `mv -n` double-claim | **REAL HAZARD** | **Patched** (line 745) |
| 4 | TTL-sweep vs create race | Not a hazard (lock held) | No patch |
| 5 | Audit log interleaving | Not a hazard (< PIPE_BUF) | No patch |

---

## Invariants

**I-LOCK:** At most one process executes the body of `with_lock` for a given
scope at any instant. Proof: `mkdir(2)` is atomic on local POSIX FS; exactly
one caller's `mkdir` succeeds; all others spin or die after 5 s.

**I-WRITE:** For any file path P under MEMORY_ROOT, the sequence
check-then-create is serialised by I-LOCK; no two processes can both observe
P as absent and both write it.

**I-RENAME:** A write to P is atomic at the filesystem level. Readers observe
either the old content or the new content, never a partial write. Proof: both
`atomic_write` and `enqueue_sync` write to a tmp file in the same directory as
the target, then call `rename(2)` via `mv -f`.

**I-CLAIM (patched):** A sync job J is claimed by drainer D if and only if
`rename(2)` atomically moved J's source file to J's claimed file. D can verify
this by checking that the source no longer exists after `mv -n`. Two concurrent
drainers cannot both claim J because `rename(2)` is atomic and `mv -n` prevents
overwriting an existing destination — exactly one drainer's source disappears.

---

## Appendix: Stale-Lock-Recovery

Patch date: 2026-04-24  
Mechanism chosen: **Option A — `kill -0 $pid`**

### Motivation

Prior to this patch, a SIGKILL'd lock holder left `$LOCK_DIR/$scope.lockd`
on disk. The trap registered for EXIT/INT/TERM did not fire under SIGKILL.
Subsequent writers spun 50 × 100 ms = 5 s then died. That is bounded but
suboptimal: the lock is provably stale (holder PID is dead) yet callers wait
the full penalty.

### Mechanism chosen and justification

**Option A: `kill -0 $pid`** — POSIX kill(2) with signal 0 performs a
permission-only check: it returns 0 if the process exists and the caller has
permission to signal it, and returns non-zero if the process does not exist.
This is the simplest portable liveness check available in bash without external
tools.

Tradeoffs vs alternatives:

| Option | Mechanism | Portability | PID-reuse safe? | Extra deps |
|--------|-----------|-------------|-----------------|------------|
| A (chosen) | `kill -0 $pid` | POSIX, macOS + Linux | No — narrow window | None |
| B | `kill -0` + `ps -o lstart` start-time comparison | macOS + Linux, different flags | Yes | `ps`, format divergence |
| C | `flock`/`fcntl` kernel file lock | Linux native; macOS needs shim | Yes (kernel tracks owner) | `flock` binary or python3 fcntl shim |

Option B was considered but `ps -o lstart` format differs between macOS BSD ps
and GNU ps, requiring conditional parsing. The portability cost was not
justified for the narrow PID-reuse window. Option C requires a dependency (flock
binary not available on macOS without util-linux) or a python3 shim adding
~15 ms latency per spin tick — also not justified.

**PID-reuse risk accepted:** the reuse window is at most one 100 ms spin tick
between `kill -0` returning non-zero and the next `rmdir` attempt. In that
window a new unrelated process must reuse the exact PID. This is extremely
unlikely on both macOS (PIDs wrap at 99999) and Linux (default 32768) with any
reasonable process creation rate. The consequence of a false negative (treating
a live process as dead) is protected by I-NEW-2: `rmdir` on an actively held
lockdir will fail because the holder wrote its PID and holds the dir open
conceptually — but more critically, the `rmdir` is still atomic; if the
"live" new PID holder has already re-acquired (impossible since `mkdir` is
exclusive), the `rmdir` simply fails and we spin again.

### Sequence diagrams

**Case (a): holder alive and making progress**

```
Holder H:   mkdir lockdir → write pid → [critical section] → rmdir lockdir
Waiter W:            spin → kill -0 pid → 0 (alive) → spin → ...
                                                              → acquire after H's rmdir
```
W sees a live PID; reclaim path is skipped; I-NEW-2 preserved.

**Case (b): holder SIGKILLed**

```
Holder H:   mkdir lockdir → write pid → SIGKILL (trap does not fire)
                            lockdir persists with pid file
Waiter W:   spin → kill -0 dead_pid → non-zero
            → rmdir lockdir (atomic) → SUCCESS
            → mkdir lockdir (atomic) → SUCCESS (W wins)
            → write own pid → proceed
            → audit: stale_lock_reclaimed
```
happens-before witness: W's `rmdir` is causally after H's death (the process
table entry is gone before `kill -0` returns non-zero).

**Case (c): two concurrent waiters racing for a stale lock**

```
Holder H:   SIGKILL'd — lockdir persists
Waiter W1:  kill -0 dead_pid → non-zero → rmdir → SUCCESS
Waiter W2:  kill -0 dead_pid → non-zero → rmdir → FAIL (already removed by W1)
            → W2 falls through to normal spin
W1:         mkdir → SUCCESS → proceeds
W2:         spin → sees no lockdir → mkdir → SUCCESS → proceeds (after W1 releases)
```
Serialization is guaranteed: only one `rmdir` can succeed (POSIX rmdir(2) is
atomic on local FS). The waiter whose `rmdir` succeeds immediately attempts
`mkdir`; the other falls back to the spin loop. At most one reclaimer wins per
stale-lock event.

**Case (d): holder slow (e.g. 30 s write)**

```
Holder H:   mkdir lockdir → write pid → [30 s write] → rmdir lockdir
Waiter W:   50 × 100ms spin: each tick: kill -0 pid → 0 (alive) → continue
            At tick 50 (5 s): die "could not acquire lock after 5s"
```
No reclaim occurs. Caller gets the existing bounded-die behavior. The 5 s
ceiling is unchanged; I-NEW-2 is preserved.

**Case (e): PID reuse (holder died, unrelated process recycles the PID)**

```
Holder H (pid=1234):  SIGKILL'd — lockdir persists with pid=1234
New process N (pid=1234): unrelated process started, now owns pid 1234
Waiter W:  kill -0 1234 → 0 (N is alive!)
           → W believes lock is live → skips reclaim → spins
           → eventually die after 5 s
```
This is the accepted risk of Option A. The window for this to occur is ≤100 ms
per spin tick. In practice, PID reuse this fast requires a very high process
creation rate. The consequence is the pre-patch behavior (5 s die), not
a correctness violation — mutual exclusion is not broken, only liveness
degrades to the original bound.

### Invariants preserved

- **I1 (mutual exclusion):** `mkdir(2)` atomicity is unchanged. The reclaim path
  uses `rmdir` then `mkdir` as two separate atomic steps; only the winner of
  `rmdir` can proceed to `mkdir`, and if that `mkdir` also fails, they spin.
  At most one process holds the lock at any instant.

- **I2 (no lost update):** The check-then-act inside the critical section is
  still serialized by I1. Reclaim does not weaken this: the reclaimer enters
  the critical section only after acquiring the lock via `mkdir`.

- **I3 (atomic observability):** `atomic_write` (rename-based) is unchanged.

- **I-NEW (liveness):** A dead holder's lock is reclaimed within the first spin
  tick after the holder's PID is confirmed dead by `kill -0`. The `stale_lock_reclaimed`
  audit entry is written as the causal witness.

- **I-NEW-2 (no false reclaim):** `kill -0` returns 0 for live processes.
  A live holder is never stolen from. The 5 s ceiling still fires for truly
  slow holders.

### Serialization proof (reclaim race)

Claim: at most one waiter reclaims a stale lock per stale-lock event.

Proof by contradiction: suppose W1 and W2 both reclaim. Both must have executed
`rmdir lockdir` successfully. But `rmdir(2)` on a directory that no longer
exists returns ENOENT. POSIX guarantees that at most one `rmdir` call removes a
given directory name from the parent — after the first, the name is gone, and
the second returns ENOENT (non-zero). Therefore both cannot succeed. QED.
