# Geertz — Thick Description of a Single Node Click

**Phenomenon:** A user, mid-session, moves their cursor over a glowing dot in the
unified visualization and clicks. One pixel-event. The thinnest possible micro-event
in the system. This audit is what that click MEANS.

## Reflexivity audit

- **Observer:** Claude (Geertz pattern), reading the codebase from outside the
  user's session. I have not watched a real user click. I am reading the click
  as text — through `streaming_canvas.js:161-186`, `node_metadata.py`, and the
  build cache shape. My description of "what the user expected" is a hypothesis
  reconstructed from the system's affordances and the project's stated goals
  (cognitive profiling, memory provenance, project narrative). Treat the
  expectation layer as triangulation-pending until field-observed.
- **Filter:** I focus on the streaming_canvas path because that is where the
  `/api/node/<id>` fetch is wired. The d3 / force-graph path (`renderer.js`)
  has its own `handleClick` and is a different ritual; I name it but do not
  thicken it here.

## Emic categories (the user's vocabulary)

| Insider term | Insider meaning | Nearest etic equivalent | Gap |
|---|---|---|---|
| "node" | a thing I made or thought about that the system remembers | graph vertex | huge — the user means a unit of *their cognitive history*, not graph theory |
| "L6 symbol" | "the deepest leaf — a function, a method, a concrete thing" | hierarchical level 6 in the AST/cluster tree | the user has internalized the level scheme as a depth metaphor |
| "hot" | "this matters / I touched it recently / it survived consolidation" | thermodynamic heat ∈ [0,1] | the user reads heat as *biographical* salience, not a float |
| "the cluster on the left" | a spatial neighbourhood the user has *learned* through repeated viewing | a region of the layout coordinate space | the layout's spatial stability is doing semantic work the user cannot articulate |
| "what does this connect to" | "what else am I going to be reminded of if I follow this" | edge set incident to node | emic question is about *expected priming*, not graph adjacency |

## Thin description (behaviour layer)

```
mousedown → mouseup within HIT_RADIUS → handleClick(e)
  → world-space hit-test against nodes Map (O(N))
  → bestId resolved
  → console.log('[stream] click', bestId, nodes.get(bestId))
  → fetch('/api/node/' + encodeURIComponent(bestId))
      → 404 → console.log; return null
      → 200 → console.log('[stream] node detail', json)
  → catch → console.warn
```

That is the entire ritual. Nothing is rendered. The "tooltip" exists only in the
DevTools console, addressed to a developer audience, not the user.

## Thick description (meaning layer)

What the user **expected** when they clicked:

> "Tell me what this node is in the story of my work. When did I last touch it?
> What domain is it part of? What other things are in its orbit? Is this the
> file I was thinking of or a different one with a similar name? Does this
> match the mental image I have of where I left off?"

The click is not a request for data. It is a **request for biographical
recognition** — the user is asking the system to confirm that this node, in
this position, with this colour, is what the user *thinks* it is. The cognitive
work the user is doing is **verification of their own mental map** against the
system's record. The click is a hermeneutic gesture: "tell me my story back
to me, indexed by this point."

What the system **provides**:

- A JSON dict (the cached node entry) printed to a console the user is not
  looking at.
- The dict contains `id, x, y, kind, domain_id` plus whatever the build worker
  stashed (`symbol_type`, `file`, `parent`, `color`, `label` — schema-dependent).
- No prose. No "you last touched this 3 days ago." No "this is one of 14
  symbols in `node_metadata.py`." No "this connects to `streaming_canvas.js`
  via your edit on April 24."
- A 404 is treated as success-with-empty (`return null`); the user gets neither
  data nor an explanation of why.

What is **culturally assumed** (the unstated curriculum the user must already
own to make sense of this gesture):

1. **Level vocabulary** — that "L6 symbol" means anything; that levels exist;
   that depth in the tree corresponds to specificity. *No on-screen legend
   teaches this.*
2. **Project naming conventions** — that `node_metadata.py` is "the new lazy
   lookup endpoint" rather than a generic name. The user supplies the meaning;
   the node id is opaque without it.
3. **Heat semantics** — that bright = recently-touched-and-surviving-decay,
   not "popular" or "important in absolute terms." Heat is a thermodynamic
   *history*, not a static rank.
4. **Layout stability as identity** — that "the cluster on the left" *is* a
   thing because the layout is deterministic enough across reloads to have
   become a place. This is a contract the visualization makes implicitly and
   that the layout-authority refactor is making explicit.
5. **Console-as-interface** — that "click → log" is a developer affordance,
   not a user affordance. Non-developer users would experience the click as
   a no-op.

## What the click is OF (the act's intent, read from context)

Clicks have at least four registers, each requiring a different response:

| Register | Emic question | What would satisfy it |
|---|---|---|
| **Curiosity** | "what is this thing?" | label + symbol kind + parent file |
| **Verification** | "is this the one I'm thinking of?" | last-touched timestamp + a 1-line gist |
| **Exploration** | "what does this lead to?" | incident edges + neighbourhood preview |
| **Debug** | "why is this *here* and not over there?" | layout provenance: cluster id, force history, level |

The current system collapses all four into the same response: *raw dict in the
console*. This is the central interpretive failure. The system has confused
**delivering data** with **answering the question that prompted the click**.

## Culture-as-text reading

- **Surface meaning:** "click reveals node detail."
- **Conventional meaning (in this codebase's code):** "click triggers a
  late-binding endpoint fetch and logs the result." The 404 fallback and the
  console-only sink reveal that the click ritual was wired *first as a
  diagnostic for the developers building the pipeline*, not as a feature for
  end users. The comment in `streaming_canvas.js:15` ("Kay's late-binding
  endpoint; 404 handled gracefully") is the giveaway: the audience is the
  next engineer, not the user.
- **Deep structural meaning:** the visualization is, today, a **debugging
  surface for the layout authority**, dressed as an end-user product. The
  click handler's existence-without-rendering is the artefact of a system
  whose meaning-structure is "prove the pipeline works" rather than "tell
  the user their cognitive history." This is not a failure — it is a stage.
  But naming it lets the next move be deliberate: either commit to the
  developer-tool reading (and dignify the console with structured output),
  or commit to the user-product reading (and render a tooltip with the
  fields above).

## Triangulation

| Source | Confirms | Adds | Contradicts |
|---|---|---|---|
| `streaming_canvas.js:174-185` | click → fetch → log; no DOM mutation | the 404 path is a "shrug" | — |
| `node_metadata.py` docstring | response is the cached node dict | "out-of-band of the layout authority on purpose" — confirms developer audience | — |
| `renderer.js:48` (force-graph path) | a *different* `handleClick` exists with `selectedNode` state and edge highlighting | the d3 path *does* render selection — so the ritual is split: streaming canvas is mute, force-graph speaks | the streaming-canvas path's silence is path-specific, not system-wide |
| CLAUDE.md ("query_methodology returns hot memories") | the user has been trained by other Cortex tools to expect *biographical* responses (narrative, story) | raises the bar: a console dict is below the user's calibrated expectation from the rest of the product | — |

## Etic analysis (analytical layer)

Three classical frames apply:

1. **Norman's gulf of execution / gulf of evaluation** — the click bridges the
   gulf of execution but the response (silent dict) leaves the gulf of
   evaluation wide open. The user cannot tell whether they hit what they
   meant to hit.
2. **Affordance vs signifier (Gibson/Norman)** — the node *affords* clicking
   (it is round, hover-coloured, in a graph) but the *signifier* of what the
   click will produce is absent. The user clicks on faith built from other
   parts of the product.
3. **Geertz's own frame** — the click is a wink, but the system reads it as
   a twitch: it processes the eyelid contraction (coordinates, hit-test, fetch)
   without registering the conspiracy (the user's biographical question).

## What this implies for the layout-authority refactor

- The streaming-canvas click path is a load-bearing seam where developer-tool
  semantics and user-product semantics meet. The refactor should pick a side
  per surface and stop pretending the same handler serves both.
- Whatever tooltip / panel the layout authority eventually renders MUST
  surface the four registers above (curiosity, verification, exploration,
  debug) as distinct response shapes — not a single dict. A render budget of
  one line per register would already be a thick description.
- The 404 fallback should not be silent. "This node was streamed but its
  detail is not in cache yet" is itself a meaningful answer to a user who
  is verifying their map.

## Hand-offs

- Hermeneutic interpretation of the response payload's field semantics → **Gadamer**
- Argument for which fields are *necessary* in the tooltip → **Toulmin**
- Quantitative measurement of click latency / 404 rate → **Curie**
- Whether the click ritual is structurally consistent with the rest of the
  system → **Beer**
- Semiotic analysis of the visual codes (colour=heat, size=level) → **Eco**
