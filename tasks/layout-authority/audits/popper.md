# Popper Falsification Audit — Layout Authority

**Test suite:** `mcp_server/server/test_layout_authority.py` (344 lines, 17 tests)
**Run command:** `python3 -m unittest mcp_server.server.test_layout_authority`
**Result:** 17 passed, 0 failed (0.225s)

## Invariants tested and outcomes

| # | Invariant | Module | Outcome | Notes |
|---|---|---|---|---|
| 1 | Slot stability — same context yields same (x, y) under repetition | geometry | **Survived** | 1000 repeats; exact equality, not approximate |
| 1b | Slot stability — interleaved kinds do not perturb prior result | geometry | **Survived** | Falsifies any shared accumulator |
| 1c | I1: every kind produces finite coords | geometry | **Survived** | Tested 11 kinds |
| 2 | O(1) state — 10^6 calls leave RSS delta < 200 MB | geometry | **Survived** | macOS `ru_maxrss` (bytes); negligible delta observed |
| 3 | P0 preempts a 1000-deep P4 backlog | scheduler | **Survived** | First pop is the P0 item |
| 3b | Strict 0..6 ordering when inserted in reverse | scheduler | **Survived** | Drain order is [0,1,2,3,4,5,6] |
| 4 | Drop counter increments exactly once per dropped submit | scheduler | **Survived** | 25 overflow submits -> dropped[P0] == 25 |
| 4b | No silent maxlen eviction (head item preserved) | scheduler | **Survived** | First popped is the original head |
| 5 | replay_since(N) returns exactly events with seq > N | log | **Survived** | Tested at 5 cut points incl. boundaries |
| 5b | replay_since(newest) is empty | log | **Survived** | |
| 6 | Overflow past cap signals gap (oldest_seq > since+1) | log | **Survived** | Used local deque swap to avoid 500k events |
| 7 | format_slot -> parse_slot roundtrip preserves structure | wire | **Survived** | Including 0.1px rounding edge cases |
| 7b | Pipe `\|` in id is rejected | wire | **Survived** | |
| 7c | kind > 32 chars rejected | wire | **Survived** | |
| 8 | NaN x rejected at wire boundary | wire | **Survived** | |
| 8b | +inf y rejected | wire | **Survived** | |
| 8c | -inf x rejected | wire | **Survived** | |

## Falsified

None on this run. All tested invariants survived a genuine attempt at refutation.

## Notable findings during test design (not falsifications, but contract gaps)

1. **Wire/protocol field-name mismatch:** `wire.format_slot` reads `slot.id`, `slot.x`, `slot.y`, `slot.kind`, `slot.domain_id` — but `layout_authority_protocol.SlotAssignment` exposes `node_id`, not `id`. A naive caller passing the protocol dataclass would `AttributeError` at the wire boundary. The test uses a local `_Slot` dataclass that matches the wire's actual contract; this exposes the gap rather than papering over it.

2. **No reference authority implementation exists yet.** Test #1 (slot stability) is therefore exercised at the geometry layer (`compute_slot`), not the authority layer. When the reference implementation lands, an additional test should re-exercise slot stability through `add_node` to falsify any non-determinism introduced at the orchestration level.

3. **Log seq is module-global and persists across `reset()`.** The replay tests reset between cases but compute expectations from observed seq values rather than assuming seq starts at 1 — this is a deliberate accommodation of the documented "seq continues across resets" invariant.

## Severity assessment

- High severity (a real bug would be caught): tests 2, 3, 4, 6, 8.
- Medium severity: tests 1, 5, 7.
- Tests with low individual severity (1c, 5b) exist as cheap consistency probes alongside the higher-severity tests in the same suite.

## Hand-offs

- Quantitative severity / power analysis -> Fisher.
- Empirical RSS profiling at 10^7 nodes -> Curie.
- Reference authority impl + integration tests -> engineer.
