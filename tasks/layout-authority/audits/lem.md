# Lem audit — possibility-space of Cortex visualizations at 10⁹ nodes

**Method.** Before predicting which visualization is "right," enumerate the
logical space of what a Cortex graph view *could* be. The current 2D neural
graph is one point; the cost-model floor (`cost-model.md` §1: 1 ns/node, 8 MB,
no per-event recompute) is the constraint envelope.

**Sources.** Lem, S. (1964). *Summa Technologiae*, ch. 4–6 (phantomatics,
ariadnology, imitology); Lem, S. (1971). *A Perfect Vacuum*.

---

## 1. The current point — P0

**P0 — single 2D scatter, kind-banded, domain-anchored.** Color = kind.
Position = `slot(domain, kind, idx)`. Vision-only. **Time axis: absent**
(timestamps in storage, not in slot formula). Cost: O(1) per node — fits
10⁹ in 1–2 s. Cannot answer: "when did this happen?", "show only my
domain", "what does a build sound like?". P0 occupies one cell of an
≥5-axis space (sensory channel × temporal axis × embodiment × medium ×
partition). The other cells exist; most are not yet built.

---

## 2. Adjacent points

### (a) Per-domain mini-graphs composing into a multigraph

Render N small canvases — one per domain — in a meta-grid. Same slot
formula with `domain_anchor = (0,0)` per tile. Meta-layer routes
cross-domain bridges (`bridge_finder.py`).

- **Per-node cost:** O(1), unchanged. Memory: lower (sparse per-domain
  buffers; only `Cortex` exceeds 10⁶). Cross-routing: O(E_bridges) ≈
  100–500. Trivially fits.
- **Verdict: feasible at 10⁹.**
- **Value: high.** "Show only my domain" without filtering — each
  domain is its own object. Cross-domain bridges become visually
  privileged, not lost in the dense scatter.
- **Tech adjacencies:** none new. `domain_origin_override` in
  `layout_authority_geometry.py` (~10 lines). Mandelbrot LOD applies
  per-tile independently. CSS Grid + `<canvas>` per domain.
- **Status: one sprint.**

### (b) Timeline-aligned (events on x, kind on y)

x = `event_seq` (or `created_at`); y = kind-band (file=0, tool_hub=1, …).
Color = domain. Append-only — new events extend the right edge; **no
reflow ever**.

- **Per-node cost:** O(1), cheaper than P0 (no idx counter). Memory:
  identical. Streaming: better — sliding 500k window matches the SSE
  log's ring buffer (`_log.py`).
- **Verdict: feasible at 10⁹** — the most Mandelbrot-friendly variant.
- **Value: very high.** Answers the questions P0 cannot: "what got added
  in the last 30 s?", "burst order?", "is this build slower?". DVR
  scrubber falls out for free — slots are pure functions of seq, and SSE
  replay-from-seq already exists.
- **Tech adjacencies:** wire format already carries `event_seq`
  (`_wire.py:21`). Need `mode=timeline` in renderer (~200 lines JS).
- **Status: one sprint.**

### (c) Audio-visual synaesthesia (sound on arrival, color on kind)

Each node-add → sonified: pitch = kind, stereo pan = domain, velocity =
burst rate. A busy build is a chord; a stalled build is silence.

- **Per-node cost in layout path:** zero (audio runs on WebAudio thread).
  Real bottleneck is the *ear*: ≤20 events/s before noise. Saturates
  long before 1 ns/node.
- **Aggregation rule:** 1 audible event per N silent ones, N adapts to
  arrival rate — Mandelbrot decimation **applied to time, not space**.
- **Verdict: feasible at 10⁹** with adaptive temporal LOD.
- **Value: medium-high, novel.** Build-progress monitoring without
  looking. Anomaly-by-ear (a stuck build *sounds* different). For the
  operator running 50 parallel builds, a force multiplier. Lem-relevant:
  *phantomatics* — alternative sensory binding to the same data.
- **Tech adjacencies:** WebAudio API (browser-native). `audio_lod.py`
  reusing the hash-keyed decimation argument from `_lod.py`, keyed on
  `event_seq % stride_t` (~60 lines).
- **Status: two sprints, low priority. Pairs with (b).**

### (d) AR/VR 3D placement

Nodes in 3D via WebXR. Domains as floating islands; symbols orbit files.

- **Per-node cost:** O(1) layout (z = `kind_band·Δz`). Memory: +33% (3
  floats vs 2). 1.5 GB at 10⁹ — exceeds 8 MB **at the renderer**, not the
  authority.
- **Renderer wall:** WebGPU instanced rendering tops at 10⁶–10⁷ nodes/
  frame. VR's 90 fps requirement (vs 60 fps) cuts per-frame budget to
  11 ms. **10⁹ is at device envelope, not algorithm envelope.**
- **Verdict: feasible at ≤10⁸ with aggressive LOD.** Bottleneck has
  moved from layout to rendering.
- **Value: speculative-high for demos, low for daily use.** VR has a
  tax (headset, calibration, motion sickness). Conflates "more channels"
  with "more understanding."
- **Tech adjacencies:** WebXR, Three.js, view-frustum-conditional LOD —
  stride becomes `f(zoom, angular_distance_from_gaze)`.
- **Status: 3+ sprints, demo not daily-tool.**

### (e) Printable static infographic

One A1 SVG/PDF poster. Domains as labelled regions; bridges as arcs.
No interactivity. For papers, slides, walls.

- **Layout cost:** unchanged, run once. **No real-time constraint** —
  can apply label deconfliction, edge bundling, hierarchical polish.
- **Print resolution wall:** A1 @ 300 dpi = 7·10⁷ printable px. 10⁹
  nodes → 0.07 px each. The medium imposes its own LOD: 10⁴–10⁵ visible
  nodes; the rest become density-shaded backdrop (DataShader).
- **Verdict: feasible at any N; the medium dominates.**
- **Value: medium daily, very high for communication.** How you explain
  the system to someone not running it. Deliverable for paper/slide/
  README.
- **Tech adjacencies:** D3 + svg.js (label deconflict), DataShader
  (existing dep, `tile-server-plan.md`), Holten 2006 edge bundling
  (~400 lines, well-known).
- **Status: one sprint v1.** Acts as *review-of-the-nonexistent*:
  writing one exposes what the graph is *for*.

---

## 3. Possibility-space table

| Variant | Per-node cost | Working set | New tech | Value | Sprints |
|---|---|---|---|---|---|
| (a) per-domain mini-graphs | O(1) | yes (lower) | none | high | 1 |
| (b) timeline-aligned | O(1) | yes (sliding) | renderer mode + DVR | very high | 1 |
| (c) audio synaesthesia | O(1) + temporal LOD | yes | WebAudio + audio_lod | med-high | 2 |
| (d) AR/VR 3D | O(1) auth, renderer-bound at 10⁹ | yes auth, no renderer | WebXR + gaze LOD | speculative | 3+ |
| (e) printable static | O(1) once + offline polish | yes | edge bundling + deconflict | high (comms) | 1 |

---

## 4. Gaps the enumeration exposes

1. **Time is missing from P0.** Variants (b) and (c) prove the data is
   there (`event_seq`, `created_at`); the renderer doesn't read it.
2. **Domain is a first-class storage object with no first-class view.**
   Variant (a) makes this explicit. Bridges from `bridge_finder.py` exist
   in storage but are not visually privileged anywhere.
3. **No non-screen output.** Variant (e) reveals the system can produce
   no artifact for someone not running it.
4. **Single-modality assumption.** Variant (c) shows the same data
   supports non-visual rendering. No `mcp_server/` module mentions audio
   — design *assumed* visual rather than *choosing* it.

---

## 5. Push-to-extreme — natural ceilings

- **(b)** at 10¹² events: x-axis px resolution becomes the wall →
  hierarchical timeline (per-day → per-second), same Mandelbrot logic on
  time.
- **(c)** with 100 parallel producers: stereo pan is 1D, can't separate
  100 sources → spatial audio (HRTF), pushes into VR territory.
- **(d)** public deployment: motion sickness, accessibility exclusion,
  hardware cost — "more channels = more understanding" breaks for some
  users.
- **(e)** live updating: contradicts the snapshot premise; the variant
  is intrinsically a frozen artifact.

Each break is informative; each marks the variant's natural ceiling.

---

## 6. Hand-offs and recommendation

- Renderer-wall feasibility at 10⁹ in 3D → **Fermi**.
- Sonic-channel information-theoretic bounds → **Shannon**.
- Timeline-LOD argument integrity → **Feynman**.
- Implementation of (a)+(b) — shared module change → **engineer**.

**Build (a) + (b) next, same sprint.** They share the geometry-module
change (per-tile origin parameter), they cost one sprint together, and
they fill the two largest gaps the enumeration exposes (domain-as-object
and time-as-axis). (c), (d), (e) are real points in the space, not the
nearest ones.
