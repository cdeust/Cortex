# Maxwell — Feedback-Stability Audit of the Layout Authority Governor

**Method:** Maxwell 1868, "On Governors." A feedback loop is stable iff every
root of its characteristic equation has a negative real part. The two
destabilisers are **gain** and **delay**.

## 1. The two governor archetypes

| Archetype | Actuator | Closes loop on producer? | Sustained-overload behaviour |
|---|---|---|---|
| **Shedding** (current Hamilton scheduler) | the *queue tail* (drops past cap) | **No** — producer rate is exogenous | Open-loop on producer; positive feedback via clients |
| **Speed-controlling** (Watt 1788, Maxwell 1868) | the *producer rate* (throttle) | **Yes** — error feeds back to source | Closed-loop; converges if gain·delay bounded |

The current `PriorityScheduler` is the first kind. `is_overloaded()` is a
*sensor only* — reported on `/api/layout/stats` but not wired into anything
that slows the build worker.

## 2. Why shedding alone is unstable here

A dropped node is not inert. Each drop has a downstream consequence that
*increases* the producer's rate:

```
  drop(node) -> renderer never sees it -> SSE retry / viewport drag re-request
              -> coalesce_subtree() refires -> request_layout(domain)
              -> build_worker re-walks domain  =>  MORE add_node    (positive fb)
```

Linearised around overload:

```
  dQ/dt    = lambda(t) - mu                              (queue dynamics)
  lambda(t) = lambda0 + k_retry * drop_rate(t - tau)     (retry feedback)
  drop_rate = max(0, lambda - mu)                        (shedding actuator)
```

Open-loop transfer `H(s) = k_retry·exp(-s·tau) / (1 - k_retry·exp(-s·tau))`
has a pole in the right half-plane the moment `k_retry >= 1` — i.e. each
drop provokes at least one re-emit. With viewport drags and SSE
auto-reconnect both refiring on missing data, `k_retry > 1` is the empirical
case. Maxwell §3 calls this "growing" oscillation.

**Verdict:** shedding is *marginally stable on bursts*, *unstable under
sustained overload*.

## 3. The speed-controlling redesign

Add an inner loop that closes on the *producer*:

```
                   +------------- error = is_overloaded -------------+
                   |                                                  |
                   v                                                  |
  build_worker --throttle.wait()--> PriorityScheduler --pop()--> authority
       |                                  ^
       +----------- emit(NodeDelta) ------+
```

- **Control variable:** build worker's emission rate per phase.
- **Set-point:** `is_overloaded(0.8) == False` — no queue above 80 % of cap.
- **Sensor:** queue lengths polled every batch boundary. *Two* thresholds —
  0.6 to engage throttle, 0.8 to disengage — give the hysteresis Maxwell §5
  requires to avoid bang-bang chatter.
- **Actuator:** `threading.Event` ("emit_permitted"). High-water crossing →
  `clear()`; build worker's next `wait()` blocks. Low-water crossing
  (confirmed for N polls) → `set()`. Binary throttle suffices because plant
  drain `mu` is approximately constant.

### Delay budget (Maxwell stability constraint)

| Source of delay | Estimate |
|---|---|
| `pop()` -> authority writes slot | ~10–50 µs |
| Sensor poll period (between batches) | 1–10 ms |
| `Event.wait()` -> `Event.set()` wakeup | ~100 µs |
| **Total loop delay τ** | **~10 ms** |

Drain `mu ≈ 200k items/s` (per `bench_layout_authority.py`). Cap headroom
between low-water and high-water on P4: `(0.8 − 0.6) × 64_000 = 12_800`.
Time to traverse at full producer rate `λ ≈ 500k/s`: `12_800 / 500_000 = 25 ms`.
**Loop delay 10 ms < band-traversal 25 ms ⇒ gain·delay margin = 2.5×.**
Stable with healthy phase margin.

If transport delay grew >25 ms the loop would oscillate at ~40 Hz.
Mitigation: poll the sensor *inside* the build worker (no SSE round-trip);
drops τ to ~1 ms and restores 25× margin.

## 4. Damping — three-poll deadband

Pure on/off throttling is bang-bang (Maxwell §5: sustains oscillation).
Damp by requiring N=3 consecutive low-water reads before re-arming
`emit_permitted`. This is a deadband + integrator — the friction-governor
analogue of Maxwell 1868 §4. Adds 3 ms to the recovery edge; prevents flap
when the queue oscillates near the threshold.

## 5. Stability classification — before vs after

| Mode | Before (shedding only) | After (shedding + speed control) |
|---|---|---|
| Transient burst (<100 ms) | damped | damped (throttle never engages) |
| Sustained overload, k_retry ≥ 1 | **growing** | damped (producer gated to μ) |
| Recovery edge | bang-bang chatter | damped (deadband absorbs ringing) |
| Catastrophic burst | growing → saturates | damped (throttle clamps at μ) |

## 6. What this preserves from Hamilton

The shedding governor is **not removed**. It remains the last line of
defence for cases the inner loop cannot reach:

- producers other than the build worker (HTTP `add_node`, MCP handlers);
- batches larger than the headroom slipping through before the next poll.

Hamilton 1969 priority-displacement is the *outer* loop (drop low-priority
under saturation). Maxwell 1868 speed control is the *inner* loop (slow the
producer before saturation). Both, layered: outer guarantees liveness,
inner guarantees stability.

## 7. Implementation sketch (minimal diff)

```python
# in PriorityScheduler.__init__:
self._emit_permitted = threading.Event(); self._emit_permitted.set()
self._low_water_streak = 0
self._LOW_WATER, self._HIGH_WATER, self._RECOVERY_STREAK = 0.6, 0.8, 3

def _update_throttle_locked(self) -> None:
    over_high = any(len(q) >= QUEUE_SIZES[p] * self._HIGH_WATER
                    for p, q in self._queues.items())
    over_low  = any(len(q) >= QUEUE_SIZES[p] * self._LOW_WATER
                    for p, q in self._queues.items())
    if over_high:
        self._emit_permitted.clear(); self._low_water_streak = 0
    elif not over_low:
        self._low_water_streak += 1
        if self._low_water_streak >= self._RECOVERY_STREAK:
            self._emit_permitted.set()
    else:
        self._low_water_streak = 0  # deadband; hold state

def wait_for_capacity(self, timeout=None) -> bool:
    return self._emit_permitted.wait(timeout=timeout)
```

Build-worker integration in `layout_worker_main.py`:

```python
for batch in build_phase(domain):
    scheduler.wait_for_capacity(timeout=1.0)     # Maxwell governor tap
    for delta in batch:
        scheduler.submit(priority_for_node(delta.kind), delta)
```

`_update_throttle_locked()` must be called from `submit()` and `pop()` while
holding `_lock` (the existing scheduler lock).

## 8. Refusal conditions raised

- **Producers other than the build worker bypass the throttle.** Stability
  is local to the gated path. HTTP `add_node` callers still need rate-limit
  middleware or the inner loop is open for them.
- **Sensor coupling assumes single-process scheduler.** Out-of-process
  deployment would replace `threading.Event` with SSE/Redis signal; re-derive
  τ — the 25× margin will not survive a 50 ms RTT.
- **`k_retry ≥ 1` is asserted, not measured.** Curie must instrument
  drop_rate vs. subsequent re-emit rate over a 60 s window to verify the
  positive-feedback claim before this audit becomes load-bearing.

## 9. Hand-offs

- **Erlang** — re-model the M/M/1 queue under the new gated arrival process;
  confirm `mu` and re-derive utilisation budget.
- **Hamilton** — keep priority-displacement; the speed controller is *added
  in series upstream*, not replacing it. Classify which non-build-worker
  producers need their own rate-limit middleware by criticality tier.
- **Curie** — measure τ end-to-end; instrument `k_retry`; validate that
  post-throttle `drop_rate` falls toward zero on sustained load.
