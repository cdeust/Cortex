# Feynman integrity audit — layout authority

Scope: the six `layout_authority_*.py` modules at
`mcp_server/server/`. The user said "5 modules"; I count six
(`protocol`, `wire`, `geometry`, `lod`, `log`, `scheduler`). I am
auditing all six. **First integrity item:** the user's count is off
by one, or the user is excluding one module from the audit and I
have not been told which. I am proceeding with all six and will flag
this at the end.

## 1. The freshman walkthrough — `add_node(NodeDelta(node_id='file:abc', kind='file', domain_id='domain:cortex'))`

The freshman thinks: "the build worker calls `add_node`, the layout
authority places the node at (x, y), the (x, y) goes to the
browser." The freshman is going to be disappointed. Here is what
actually happens, line by line, when you trace it through the code
that is currently checked in:

1. The build worker calls `authority.add_node(delta)`.
2. **`authority` doesn't exist.** `layout_authority_protocol.py`
   defines a `Protocol` (line 142) and a factory
   `authority_from_geometry()` (line 222) that does
   `from mcp_server.server.layout_authority import build_authority`.
   That module is not in the tree. `find` confirms no
   `layout_authority.py` (only the six `layout_authority_*.py`
   suffixed modules). **The integrator does not exist.** Every
   chain of reasoning below is what *would* happen if it were
   written and wired correctly to the six modules; it is not what
   happens today, because today nothing calls `add_node` at all.
3. Assume the integrator exists. `add_node` would:
   a. Validate `kind in NODE_KINDS` (frozenset at line 30 of
      `protocol.py`) — `'file'` is in the set, OK.
   b. Validate per-kind preconditions from the `NodeDelta`
      docstring (lines 59–66). For `kind='file'`,
      **`parent_id` SHOULD be the primary tool_hub id "if known"**
      — the docstring says optional. So `parent_id=None` is legal
      and the file will land somewhere without a tool hub.
   c. Compute the priority: `priority_for_node('file')` →
      `PRIORITY_FILE = 2` (`scheduler.py` line 90, 103).
   d. Call `scheduler.submit(2, delta)`. If queue P2 (cap 16k)
      isn't full, it appends and notifies the consumer. If full,
      it returns False and increments `_stats.dropped[2]`. **No
      exception, no log line that I can see in the scheduler.**
      That is a silent drop unless a layer above checks the bool.
4. The consumer thread (also in the missing integrator) does
   `scheduler.pop()`, gets `(2, delta)`, and computes geometry.
5. Geometry needs a context dict (`compute_slot`, `geometry.py`
   line 183). For `kind='file'` it needs `anchor`, `hub_angle`,
   `idx`, `total`. **Where do these come from?**
   - `anchor` = the (x, y) of `domain:cortex`. That requires
     having previously processed an `add_node(kind='domain',
     node_id='domain:cortex')` and stored its anchor. The
     protocol invariant **I7** (line 212) explicitly allows the
     domain to arrive AFTER its members and says members get a
     "placeholder anchor" with **no retroactive reseat**. So if
     `domain:cortex` hasn't landed yet, the file is placed at
     some placeholder forever. **This is implicit — the freshman
     would expect the file to be reseated when the real domain
     arrives. It is not.**
   - `hub_angle` = the angle of the file's primary tool hub.
     Our delta has `parent_id=None`. So `hub_angle` is undefined.
     Invariant **I4** (line 198) covers this: the file falls back
     to "the domain hub" with no retroactive reseat. The freshman
     would expect that "place me near my tool" — the code says
     "if you didn't tell me your tool, you don't get one, and you
     won't later either." That is a real product decision; it is
     not in any visible comment near `slot_for_file`.
   - `idx` and `total_in_hub` = "this file's index among files in
     the same hub" and "running total of files in that hub." The
     scheduler/geometry modules **do not maintain these
     counters**. The integrator (which doesn't exist) is supposed
     to. The geometry module's docstring says O(domains × kinds)
     counters live there; the file is silent on who keeps them.
6. `compute_slot` returns `(x, y)`. It is finite by construction
   *if* anchor/hub_angle/idx/total are finite. There is no
   `_validate_finite` inside `compute_slot`. That validation
   happens later in `wire.format_slot`. **Magic #1:** the
   geometry code trusts its caller to pass finite floats. Pass
   `total=0` to `slot_for_setup` — protected by `max(total, 1)`,
   OK. Pass `nan` for `outward` — propagated to `cos`/`sin`,
   produces nan. The wire layer would then `raise ValueError`,
   and the producer thread would crash unless somebody catches.
   **Whether anyone catches is an integrator-layer question and
   we can't audit it because the integrator does not exist.**
7. Construct `SlotAssignment(seq=N, node_id='file:abc', x=X,
   y=Y, kind='file', domain_id='domain:cortex')`.
8. Hand the `SlotAssignment` to `wire.format_slot(seq, slot)`.
   **Bug:** `wire.format_slot` reads `slot.id` (line 103). The
   `SlotAssignment` dataclass at `protocol.py` line 124 names
   the field `node_id`, **not** `id`. `format_slot` will raise
   `AttributeError`. Same for `_validate_id(slot.id, ...)` line
   103. **This is a hard, demonstrable bug.** It is not "magic";
   it is a contract divergence between the protocol module and
   the wire module that both call themselves the source of truth
   for the `SlotAssignment` shape. The `_benchmark()` function
   at the bottom of `wire.py` defines its OWN local `_Slot` with
   field `id` (line 209) — which is how the benchmark passes,
   masking the bug.
9. `format_slot` returns SSE-framed bytes.
10. Bytes go to `log.emit('slot', payload_bytes)` (`log.py` line
    119). It increments `_event_seq`, appends to a deque (cap
    500_000), fans out to subscribers via `put_nowait`, and
    reaps subscribers with >200 misses.
11. SSE handlers (in some other module — not audited here, also
    likely missing) drain their queues and write to sockets.

**Net result of one `add_node` today:** nothing, because no
integrator exists. **Net result if the integrator were written
the obvious way:** an `AttributeError` at step 8 because
`format_slot` and `SlotAssignment` disagree on the field name.

## 2. `add_edge(EdgeDelta(source_id='file:abc', target_id='tool_hub:Edit', kind='tool_used_file'))`

1. `add_edge` validates `kind in EDGE_KINDS` (line 35).
   `'tool_used_file'` is in the set.
2. Per the docstring (line 86–94), the edge is buffered if
   either endpoint hasn't been added yet. **There is no
   buffering code in any of the six modules I read.** The
   docstring says "the authority tolerates out-of-order arrival
   by buffering" and references invariant I5 (pending-edges
   buffer, default 100k). I5 lives only in the docstring text.
   **The buffer does not exist as code in the audited files.**
   It must live in the (missing) integrator.
3. Submit at `PRIORITY_EDGE = 5` (`scheduler.py` line 93). Cap
   128k. Drops silently when full.
4. Consumer pops, calls `wire.format_edge(seq, edge)`. This
   one **does** match the protocol (`source_id`, `target_id`,
   `kind`). It encodes `<source>|<target>|<kind>` and ships.
5. Edge goes to `log.emit('edge', bytes)`. Same fan-out.
6. **No SlotAssignment is emitted for an edge.** This matches
   the protocol postcondition (line 92). Good.

**Magic call-out:** the build worker docstring (`protocol.py`
line 89) says the worker "SHOULD emit nodes before edges" but
"the authority tolerates out-of-order arrival by buffering."
That tolerance does not exist in the code. If the integrator
forwards an edge whose endpoints haven't landed, the *renderer*
will draw a line to a phantom node-id. I cannot tell whether
the renderer handles that or shows nothing or crashes —
that's the JS side, out of scope. But "tolerates" is a claim
the audited code does not back up.

## 3. `request_subtree(domain_id='domain:cortex')`

1. Calls `scheduler.coalesce_subtree('domain:cortex')`
   (`scheduler.py` line 186). Linear scan over P6 (cap 100); if
   already pending, returns False; else appends and notifies.
2. Consumer pops at priority 6 (deferred behind P0–P5).
3. **Then what?** The integrator is supposed to walk the stored
   nodes for that domain and re-emit a SlotAssignment for each.
   The audited code does NOT contain that walk. The geometry
   functions are pure and stateless; the log is append-only and
   bounded; the scheduler hands you a `domain_id` string. Some
   third store (the "main store" referenced in `scheduler.py`
   line 154) is presumed to exist in the integrator. **Magic.**
4. Per protocol I2 (line 187), re-emitted slots get higher seq
   numbers; clients update by seq. That's clean. But the
   "re-emit slot assignments for one subtree" behavior, the
   verb the user named, lives entirely in code that is not in
   the repo.

## 4. Divergences between claim and code

- **Missing integrator:** `protocol.py` line 229 imports
  `from mcp_server.server.layout_authority import
  build_authority`. That module does not exist. The factory is
  a forward-declaration to a file that has not been written. No
  test in `test_layout_authority.py` could exercise the wiring
  end-to-end.
- **Field-name divergence (hard bug):** `wire.format_slot`
  reads `slot.id`; `protocol.SlotAssignment` exposes `node_id`.
  An `AttributeError` is the first thing the producer would
  hit. The wire benchmark hides this with a local `_Slot`
  dataclass that uses `id`.
- **Pending-edges buffer (I5) referenced but not coded.**
  Invariant I5 at `protocol.py` line 205 says the buffer has
  cap 100k and drops oldest. No buffer exists in the six
  modules.
- **Edge-endpoint preconditions claimed but not checked.**
  `EdgeDelta` docstring (line 86) says endpoints "MUST" have
  been previously `add_node`'d. Nothing in the wire, scheduler,
  or log layers checks this. Enforcement, if any, is the
  missing integrator's job.
- **`reset()` semantics fixed, then disagreement preserved.**
  `log.py` line 217 acknowledges the spec docstring and the
  spec code body disagreed about whether `_event_seq` resets.
  The maintainers chose the "seq continues" behavior in code
  and documented the choice (good). This is correctly handled
  but is a divergence the next reader needs to know about.
- **No retroactive reseat (I4, I7) is presented as an
  invariant, but a freshman would call it surprising.** A file
  that arrives before its tool hub is permanently misplaced.
  The user explicitly refused punted-to-frontend layout work
  earlier today; this is a server-side equivalent of "we don't
  fix it, you live with it." It is a real product decision and
  it is documented; calling out for honesty: it is also a
  source of permanent placement errors when streaming order
  isn't perfect.
- **Wire-layer `format_done` totals are passed in by the
  caller** (`wire.py` line 139). The wire layer does not count
  what it has emitted. The caller — the missing integrator —
  must keep that total. If it's wrong, no one notices.
- **`scheduler.submit` returning False is silent at the API
  surface.** The integrator must observe the return. Otherwise
  drops are real but uncounted at the call site.

## 5. Self-deception check

- My investment: "find issues and report them honestly." Risk:
  overclaiming bugs that are integrator-layer questions I can't
  see because the integrator doesn't exist. I've marked every
  such claim with "magic" or "missing integrator."
- Rederived `add_node` from code without reading the sibling
  audits in this directory. Disagreement with them is evidence
  of either my error or theirs.
- Highest-impact invalidator: a `layout_authority.py` exists
  somewhere I didn't search. `find ... -name layout_authority.py`
  across both worktrees returned empty. If wrong, audit changes.

## 6. Honest summary

**What is known:** the six modules each compile in isolation,
have clean docstrings, and (for geometry, lod, scheduler, log)
are internally consistent. The wire layer has a hard
field-name bug against the protocol it claims to encode.

**What is uncertain:** every behavioral claim about
`add_node`, `add_edge`, `request_subtree` end-to-end is
uncertain because the integrating module does not exist.

**What surfaced that wasn't in the original claim:** there is
no `layout_authority.py`. The factory `authority_from_geometry`
is unwired. The pending-edges buffer (I5) is documented in
prose only. The user's "5 modules" count is off by one.

## 7. Hand-offs

- Implementation of `layout_authority.py` integrating the six
  modules → engineer.
- Definition of where `idx`/`total` counters live → architect
  or engineer; pick one module to own the per-(domain,kind)
  counter map.
- Fix `wire.format_slot` to read `slot.node_id` (or rename the
  protocol field) → trivial, but choose which side moves.
- Verification that `request_subtree` actually re-emits
  slots → measurement (Curie).
