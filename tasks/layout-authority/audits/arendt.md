# Arendt thoughtlessness audit — Cortex layout authority

System: `mcp_server/server/layout_authority_{protocol,scheduler,wire,log,geometry,lod}.py`.
Method: at each silent failure, name the *suppressed question* whose absence let "I was
just following the contract" substitute for thinking. Arendt: harm produced in the spaces
between roles, each module honoring its half, the inconvenient question passed across
the boundary until it lands on no one. Stakes **High**; coding-standards 1,2,7,8 apply.

## Finding 1 — Build worker dies mid-emit

**Suppressed question:** what is the lifecycle of `_event_seq` and the subscriber set when
the producer thread crashes between `emit()` calls?

**Silent failure:** `layout_authority_log.emit()` documents a "single-producer precondition"
load-bearing for I1, I2. Nothing enforces it; nothing detects its violation. Subscribers
keep draining a queue that will never receive `'done'`. `replay_since(N)` returns the same
finite prefix forever.

**Visible symptom:** UI hangs at "streaming…" indefinitely. No browser error, no server
error, healthy-looking subscriber.

**Engineering response:** producer heartbeat — worker emits `'heartbeat'` every `T`
seconds; log records `last_emit_monotonic`; SSE handler converts silence > `5*T` into an
explicit `event: producer_lost` frame. Client distinguishes slow build from dead producer.

## Finding 2 — `add_node` arrives with kind not in `NODE_KINDS`

**Suppressed question:** who is the trusted producer of `NodeDelta`, and what happens when
that trust is misplaced?

**Silent failure:** protocol says "raises `ValueError`." The build worker is in another
thread; an unhandled `ValueError` kills it. The authority's ingress disappears. Worker
assumes authority validates; authority assumes worker validated; both right, neither
catches the dropped frame. Classic Eichmann shape: each role just doing its job.

**Visible symptom:** stream stops at a random point. Downstream symbols never emitted.
`producer_alive` (F1) eventually goes false.

**Engineering response:** validation is a *boundary* concern, not a shared assumption.
Input wrapper catches `ValueError`, logs once per kind, increments `rejected_by_kind[kind]`,
proceeds. Contract changes from "raises" to "drops with counter." `/api/layout/stats`
exposes `rejected_by_kind` — the inconvenient question becomes a graph.

## Finding 3 — SSE client at 100% CPU cannot drain

**Suppressed question:** what is the user experience of the 201st failed `put_nowait`?

**Silent failure:** at `_DEAD_QUEUE_MISS_THRESHOLD = 200` the subscriber is reaped
silently. No `event: evicted` delivered (queue is full — the condition that triggered
eviction). Handler discovers it only when next `q.get()` blocks forever. User reloads,
gets fresh stream from `seq=current`; events between eviction and reload simply missing —
`replay_since` reports no gap because the client never knew its last-good seq.

**Visible symptom:** graph silently desyncs. Some nodes placed; others emitted during the
eviction window never appear. User blames "flaky network."

**Engineering response:** before reaping, set HTTP trailer `X-Cortex-Evicted: 1` on close
OR enqueue a tombstone the handler observes via the unbounded read side. Browser treats
either as "you missed events; do a fresh snapshot fetch."

## Finding 4 — Replay-buffer overflow with unwritten encoder

**Suppressed question:** what does a client requesting `Last-Event-ID: 12345` actually see
when the buffer has rolled past 12345?

**Silent failure:** `replay_since` returns `([], oldest_seq)` on overflow; docstring says
"SSE handler emits a `replay_lost` sentinel." `layout_authority_wire.py` defines
`format_slot/edge/done`. **There is no `format_replay_lost`.** Whatever the handler
improvises is invented at the call site. Protocol wrote a contract; wire wrote encoders;
log wrote a gap signal; nobody wrote the encoder for the gap signal — each author thought
another module would.

**Visible symptom:** stream silently truncates, client sees stale graph, or browser parses
malformed event and EventSource closes with generic error.

**Engineering response:** add `format_replay_lost(seq, oldest_seq) -> bytes`. Document
at protocol layer that this is a first-class event, not a sentinel. CI test asserts every
event-kind named in any docstring has an encoder.

## Finding 5 — `compute_slot` falls back to anchor on unknown kind

**Suppressed question:** if `node_kind` is not in any branch, what does the renderer do
with N nodes placed at exactly the same `(x, y)`?

**Silent failure:** dispatcher's last line returns `ctx.get("anchor", ...)`. Docstring
celebrates "safe fallback so the renderer never sees NaN." Renderer doesn't see NaN — it
sees N nodes piled on the domain anchor, occluding the hub, click targets all hitting the
topmost. "Safe" is floating-point safe, not semantic. The thinking — *what does it mean
for an unknown kind to be placed?* — was outsourced to a `ctx.get` default. New kinds
added to `NODE_KINDS` but not to `compute_slot` produce clumps; cause invisible — no
warning, no counter.

**Visible symptom:** clumps on the domain hub when a new kind is added without a geometry
branch. No diagnostic.

**Engineering response:** terminal branch raises `NotImplementedError`. Boundary (F2)
classifies as rejection, increments `rejected_by_kind`. CI test enumerates `NODE_KINDS`
and asserts every kind has a non-fallback branch.

## Finding 6 — `reset()` clears subscribers without telling them

**Suppressed question:** what does the subscriber's handler think happened when its queue
stops receiving events at the moment a fresh build starts?

**Silent failure:** `reset()` calls `_subscribers.clear()` and returns. Subscriber queue
still exists; handler still holds reference; still calls `q.get()` and blocks. New
build's `emit()` fans out to the (empty) subscriber set. Old clients hang as in F1 — but
producer is *alive*, just unaware they exist. Compounds with F1: per-subscriber
keepalives keep firing, client believes stream healthy while build it watches no longer
exists.

**Visible symptom:** during re-build (file save → reset → new emit) existing tabs
continue showing the previous build's nodes indefinitely. User must hard-refresh. The
"live" promise silently broken.

**Engineering response:** before clearing, fan out a synthesized `event: reset` to each
subscriber, then clear. Browser treats it as "drop graph, reconnect from seq=0." Add
`format_reset`. Reset becomes a *spoken* boundary, not a silent disappearance.

---

## Cross-finding pattern

Five of six failures share one shape: **a contract was written, each module honored its
half, and the question "what if my counterparty is wrong, absent, or interrupted?" was
passed across the boundary in both directions until it landed on no one.** The
bureaucratic geometry Arendt diagnosed: every role correctly performed; harm produced in
the spaces between roles.

Remediation is uniform: **promote the silent boundary into a first-class event**
(`heartbeat`, `evicted`, `replay_lost`, `reset`) and **add a counter** for every drop
path. A counter nobody reads still beats a drop nobody can name. The counter is the
durable artifact (work, in Arendt's sense) that survives the labor cycle of streaming.

## Hand-offs

- Producer-aware health signaling → **Hamilton** (resilience with judgment at boundaries).
- Counter & observability surface → **Deming** (variation made visible).
- Encoders (`replay_lost`, `reset`, `evicted`, `heartbeat`) → engineer.
- CI test that `NODE_KINDS` ⊆ `compute_slot` branches → engineer.

Diagnosis only. Redesign belongs to agents that own system design.
