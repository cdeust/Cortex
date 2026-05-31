# Bateson — Levels-of-Context Audit of the Layout Authority

> The pattern that connects is not at any single level — it is the
> relationship between levels. A signal that reads as `error` at level
> *n* can be invisible, or re-encoded as health, at level *n−1*.

The layout authority is a five-level system. Each level has its own
notion of error, its own corrective feedback, and its own time
constant. The pathology this audit hunts is the **double bind** that
emerges when level *n*'s corrective move *is the very thing* that
produces a level *n+1* fault — and the producer cannot
meta-communicate the contradiction.

## L1 — Individual events

Unit: one `(seq, kind, payload)` tuple emitted by `_log.emit`
(`layout_authority_log.py:46`). Time constant: ~250–300 ns
(fermi.md). Producer: single worker thread (load-bearing
single-producer rule, `_log.py:24–32`).

| Question | Answer |
|---|---|
| Error? | `ValueError` from `_protocol`; `put_nowait` full on subscriber; `kind ∉ NODE_KINDS`. |
| Corrective | Drop + `_event_log_drops += 1`; or buffer in scheduler P5 (dijkstra.md §1). |
| Time | Sub-µs. |

The *pattern* of drops (L2 concern) is invisible here because each
drop is locally legitimate.

## L2 — Event streams (one SSE channel, one client)

Unit: one subscriber `queue.Queue` + socket. Time constant: browser
frame budget (~16 ms) and TCP RTT.

| Question | Answer |
|---|---|
| Error? | `put_nowait` miss; >200 consecutive misses ⇒ auto-evict (`_log.py:43`); `Last-Event-ID` gap outside 500k ring (`_log.py:14`). |
| Corrective | Auto-evict dead subscriber; client reconnects with `Last-Event-ID`; on miss-window-exceeded, fall back to full re-stream from build cache. |
| Time | ~200 events (~2–7 ms at peak). |

**Invisible at L1**: the eviction policy reads, at L1, as "queue full
→ drop event." A *slow client* (laptop on battery) emits the same L1
signal as a *crashed* client. L2's corrective is identical in both
cases. The producer never learns which failure mode it papered over.

**Double-bind seed (L1↔L2)**: producer's content message is "I
produce at line rate." Relationship message implicit in eviction is
"I silently disconnect anyone who can't keep up." A slow consumer
cannot meta-communicate "please slow down" because the SSE wire is
one-way (`_wire.py` is encoder-only — coase.md §3c). By design at L2;
becomes the trap at L4.

## L3 — Build cycles (one full sweep)

Unit: one `recompute_layout` invocation (`recompute_layout.py:46`)
or one in-process authority sweep. Time constant: 90 s–3 min for 1M
DrL (`layout_engine.py:8–17`).

| Question | Answer |
|---|---|
| Error? | `igraph_missing` 503; `no_graph_cached`; `empty_graph`; layout writing 0 rows. |
| Corrective | Skip-if-fresh on fingerprint match (`recompute_layout.py:86–99`); fall back to legacy URL when extras absent (`open_visualization.py:217`); full rewrite per run (`layout_pg_store.py:54`). |
| Time | One sweep (minutes). |

**Invisible at L2**: a build that "succeeds" but writes degenerate
geometry (e.g. all coords collapsed because DrL diverged) emits
well-formed L1 events and clean L2 streams. Pathology only surfaces
at L5. There is no L3 health metric on geometric *quality* — the
fingerprint protects topology equivalence, not visual fitness.

**Double-bind seed (L2↔L3)**: L2 promises "events flow at line rate."
L3 promises "topology change ⇒ recompute." During a 3-min DrL pass
L2 serves a *previous* fingerprint's coords while L3 is mid-flight.
Clients see consistent old data, then a sudden flip. No level emits
"stale-but-consistent" as a distinct state from "fresh."

## L4 — Session lifetime (one server lifecycle)

Unit: one `cortex-visualize` launch → 10-min idle shutdown
(`open_visualization.py` schema). Time constant: minutes to hours.

| Question | Answer |
|---|---|
| Error? | Plugin cache out of sync (mitigated by `_auto_sync_all_caches`, `open_visualization.py:84`); zombie on port 3458 (mitigated by `_kill_port`); bootstrap exit non-zero; PG `batch_pool` exhausted; idle-shutdown firing while DrL still runs. |
| Corrective | Best-effort rsync to every cache root; SIGTERM port-holder; bootstrap status surfaced as MCP message; *no* corrective for a layout pass interrupted by idle-shutdown. |
| Time | Single-shot per launch; user re-launches manually. |

**Invisible at L3**: idle-shutdown that races a 3-min DrL pass emits
L3 = "no error, just nothing written." Next launch sees stale
fingerprint → recomputes → races shutdown again. Livelock with zero
L1/L2/L3 errors, only L5 symptom "viz never finishes."

**Double bind in full bloom (L2↔L4)**: L2 "drop slow subscribers"
combined with L4 "shut down on idle" means a subscriber *evicted for
being slow* contributes zero traffic, contributes to "idle," and
triggers shutdown of the build it was waiting on. Eviction silenced
the only signal that would have kept the server alive. No actor can
name this — `_log` doesn't know about idle-shutdown; the launcher
doesn't know about subscribers.

## L5 — System / user experience

Unit: one user session in front of one tab. The level Bateson calls
"the ecology" — where the system's mind lives.

| Question | Answer |
|---|---|
| Error? | "The graph looks fragmented." "It froze." "Nodes pop in and out." |
| Corrective | Out-of-band: user reports, lessons.md, this audit. **No in-band channel.** |
| Time | Days (next code change). |

**Invisible at L4**: every L1–L4 signal reads as health. Producer at
line rate, streams draining, build fingerprint-fresh, server up. User
suffering. Canonical Bateson pattern — **the symptom lives at the
level that has no voice in the loop.**

## The double bind, named

Three conditions (Move 2):

1. **Contradictory messages at different levels**: L2 says "fast
   subscribers win, slow get dropped." L5 says "every user sees the
   whole graph." A user on weak hardware *cannot satisfy both*:
   keeping up means dropping detail (LoD collapse,
   `layout_authority_lod.py`); receiving detail means eviction.
2. **Cannot leave the field**: MCP handler awaits `_prepare_layout`
   up to 600 s (`open_visualization.py:257`). Closing the tab does
   not close the build.
3. **Cannot meta-communicate**: SSE wire is one-way (coase.md §3c).
   The client has no protocol verb for "I am slow, please coalesce"
   short of dropping the connection — which the server reads as
   "client gone, evict."

**All three hold.** The pattern is structural, not a bug in any module.

## Pattern that connects

| This system | Isomorphic to | Solution domain |
|---|---|---|
| Slow-subscriber eviction → idle-shutdown livelock | TCP silly-window syndrome | Window-scaling + Nagle/Clark — *negotiation* primitive in the wire. |
| L3 fingerprint hides bad geometry | Compiler type-checks hide semantic bug | Property tests at L3 boundary. |
| L5 invisible at L1–L4 | Microservice "all green" while users error | RUM / synthetic probes at L4 entry. |

## Structural interventions (no individual blame)

1. **Open the L2 back-channel.** One-bit consumer-pressure token from
   client → server (e.g. ping carrying `keep-coalescing`, or tiny
   POST every N frames). Producer reads "alive and slow," not "evict."
   Resolves bind condition 3.
2. **Couple L4 idle to L2 backlog.** Idle-shutdown counts a
   subscriber whose queue depth > 0 as *not idle*, even if no bytes
   left the wire in 30 s. Breaks eviction→silence→shutdown.
3. **Add L3 geometric-health gate.** Before
   `write_layout` commits (`layout_pg_store.py:54`), assert
   `span > ε` on coords. Degenerate layouts become L3 errors instead
   of invisible L5 symptoms.
4. **Promote L5 into the loop.** Synthetic headless render per launch
   reports back. L5 acquires a voice; system stops being a black box.
5. **Type-distinguish "stale-consistent" from "fresh."** Build cache
   exposes `(fingerprint, version, age_s)`; L2 events carry explicit
   `stale=true` rather than serving old coords as if current.

## Compliance check (against `~/.claude/rules/coding-standards.md`)

| Rule | Status | Note |
|---|---|---|
| §1 SOLID | pass | Each intervention adds one responsibility per module. |
| §2 Layer dependency | pass | Back-channel in `_wire`, geometric gate in `core.layout_engine`, L5 probe in handlers — no inversions. |
| §7 Local reasoning | conditional | Intervention 1 makes the wire bidirectional; pair with Dijkstra to keep the protocol enumerable. |
| §8 Sources | pass | Anchors cite coase.md §3, fermi.md, dijkstra.md §0–§2, and inline source files. |

## Hand-offs

- **Dijkstra**: formalize L2 back-channel with enumerable verbs; protect H1/H2.
- **Meadows**: model L2-eviction → L4-idle → L3-restart feedback loop.
- **Coase**: re-evaluate IPC boundary if intervention 1 moves work to its own thread.
- **Engineer**: implement intervention 3 (geometric-health gate) first — lowest blast radius, highest L5→L3 visibility gain.
