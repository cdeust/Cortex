# Hopper Audit — A Slot DSL for the Layout Authority

Scope: the protocol boundary between the build worker and the layout
authority (`layout_authority_protocol.py`). What follows is a
compile-as-abstraction-barrier proposal: lift the build worker out of
event-stream vocabulary into domain vocabulary, and let a tiny
translator emit the deterministic stream the authority already expects.

## 1. The vocabulary mismatch

The build worker thinks in **batches**: "I walked file F and produced
8000 symbols, all children of F, all in domain D." The authority's
input language thinks in **events**: singular `NodeDelta` calls with
implicit ordering against I3 (parent file before child symbol), I4
(file slot is final), and I7 (domain present before its members).

The build worker translates from its native vocabulary (batches keyed
by `(domain, kind, parent)`) into the authority's vocabulary by hand,
at every call site. That is where the I3/I4/I7 violations enter the
system — exactly the shape of problem compile-as-barrier addresses.

## 2. Today: build-worker code without the DSL

```python
# Build worker — current, pre-DSL. The author is bookkeeping ordering
# rules that the protocol declared NORMATIVE. Easy to get subtly wrong.

def emit_file_and_symbols(authority, domain_id, file_path, symbols):
    file_id = f"file:{domain_id}:{file_path}"
    # I7: domain must precede its members. Hope it was already added.
    # I4: file slot is FINAL — no retroactive reseat. Get it right now.
    authority.add_node(NodeDelta(
        node_id=file_id, kind="file", domain_id=domain_id,
        parent_id=None,            # tool_hub may not be known yet
    ))
    # I3: every symbol must arrive AFTER its parent file. Author has
    # to remember to emit the file FIRST. If the author groups symbols
    # by domain instead of by file, parent-pending buffer fills up.
    for sym in symbols:
        authority.add_node(NodeDelta(
            node_id=f"sym:{file_id}:{sym.name}",
            kind="symbol",
            domain_id=domain_id,
            parent_id=file_id,
        ))

# At the call site, the author is also reasoning about backpressure:
# I6 says add_node is non-blocking and may drop. So the author
# *should* check counter deltas, but in practice nobody does.
```

Failure modes the author must hold in their head: I3 ordering, I4
finality, I5 pending-edges overflow, I6 drop counters, I7 domain
precedence, plus the per-kind preconditions in `NodeDelta`. Every
new call site re-derives them.

## 3. With the DSL — domain vocabulary, translator does the rest

```python
# Build worker — post-DSL. The author thinks in batches, by domain.
# The translator emits the event stream and enforces I3/I4/I7.

with authority.batch(domain_id="cortex") as dom:           # opens domain
    with dom.kind("file") as files:                        # batch of files
        for path in walk_repo():
            f = files.add(path, parent_tool_hub="Edit")    # returns handle
            with f.kind("symbol") as syms:                 # nested batch
                for sym in parse(path):
                    syms.add(sym.name)
            # __exit__ on syms flushes 8000 symbols in deterministic
            # order, AFTER f's slot has been requested. I3 honored.
        # __exit__ on files flushes pending I4 reseat-prevention.
    # __exit__ on dom guarantees domain anchor was emitted before
    # any of the kind-batches inside. I7 honored.
```

Or, the decorator form for the common case "I have a list, please
emit it as a batch":

```python
@authority.emit_batch(domain="cortex", kind="symbol", parent=file_id)
def all_symbols_in(file_id):
    yield from extract_symbols(file_id)   # yields names; DSL handles ids
```

The author writes domain logic. They never type `NodeDelta`. They
never reason about seq, pending-edges, or parent-pending buffers.

## 4. What the abstraction barrier buys

**Ordering invariants compiled in, not asserted at the API boundary.**
The author cannot emit a symbol before its parent file because the
only way to add a symbol is inside `f.kind("symbol")` where `f` is
already an emitted file handle. Dijkstra's audit lists I3/I4/I7 as
"partial testable, requires single-producer construction argument."
With the DSL, they become properties of the DSL's small surface, not
of every call site.

**Backpressure visible at the batch boundary, not per-event.** Each
context carries `dropped` and `pending` counters; `__exit__` returns
a summary (`emitted=8000, dropped=0, pending_edges=0`). The Hopper
"tangible quantity" move applied to backpressure: 8000 symbols is
countable; 8000 individual `add_node` return values are not.

**Priority-aware batched submit.** Today the worker emits in source
order; the scheduler re-prioritizes (P2 file < P4 symbol). The DSL
knows the batch shape ahead of time; it can hand the scheduler a
single `submit_batch` with P2 items first, then P4 items, eliminating
the parent-pending buffer for the common in-order case — a direct hit
on Dijkstra's B1 (residency exceeds the 8 MB cost-model ceiling).

**The author's failures become the DSL's tests.** I3 violation today
is a per-call-site latent bug. With the DSL, I3 violation is
impossible by construction unless the DSL itself is wrong — and the
DSL has one implementation that one team audits. Hopper's second move
(debugging as first-class): not adding a tool to find the bug,
removing the place the bug can occur.

**Protocol evolution without forking call sites.** New node kinds or
new ordering obligations (I8, I9) are absorbed by the DSL; call sites
do not change. The same property that let COBOL programs survive five
generations of hardware.

## 5. Risks and refusals (zetetic)

- **Domain formalizability.** The DSL is only as good as the formal
  semantics of the batch grammar. The grammar must be specified
  explicitly (which contexts may nest in which, what `__exit__` is
  obligated to flush, what happens on exception inside a `with`). If
  the spec is ambiguous, the DSL is a leaky abstraction worse than no
  DSL. **Required artifact:** `slot_dsl_grammar.ebnf` plus an ADR
  before the DSL is merged. Hand off to **Shannon** for formalization
  if the grammar drifts during implementation.
- **Premature abstraction.** §3.3 of the coding standards: three
  concrete uses before extracting. Today there are at least four
  call sites that hand-roll the file→symbol pattern (AST walker,
  conversation ingester, memory ingester, knowledge-graph builder).
  The threshold is met. If a future audit finds only one user, the
  DSL is premature and should be rolled back.
- **Performance.** Per-event budget at 10⁹ nodes / 1–2 s is ~10 ns.
  Context-manager overhead in CPython is ~200 ns per `__enter__` +
  `__exit__`. The DSL's `with` blocks must therefore wrap **batches**,
  never individual nodes. The decorator form (`@emit_batch`) is the
  preferred high-volume API; the nested `with` form is for human
  authoring at the call site, where batches are intrinsically large.
  Single-node DSL invocation must be refused at construction.
- **Exception semantics.** Two options: (a) flush partial batch and
  propagate (at-least-once); (b) discard (transactional). Option (a)
  matches the authority's "keep going on producer failure" stance.
  Decide in the ADR; do not let it be implementation-defined.
- **"Ask forgiveness" check.** Bounded risk (strict additive layer;
  old `add_node` keeps working); demonstrable benefit (I3/I4/I7 by
  construction); no safety bypass; ownership — pass. Proceed.

## 6. Compile-as-barrier compliance check

| Rule | Status |
|---|---|
| User vocabulary identified (domain/kind/parent batches) | PASS |
| Implementation vocabulary identified (NodeDelta event stream) | PASS |
| Translator scope is well-defined (DSL grammar) | PENDING — needs grammar ADR |
| Domain admits formal semantics | PASS — finite kinds, finite nesting |
| Debugging elevation: invariants enforced by construction | PASS |
| Tangible quantities at batch boundary (emitted/dropped/pending) | PASS |
| Three concrete users before extraction | PASS — four call sites |

## 7. Hand-offs

- DSL grammar formalization → **Shannon** (or **Panini** if available
  for grammar work).
- Correctness-by-construction proof of I3/I4/I7 from the DSL's
  context-manager semantics → **Dijkstra** / **Lamport** (TLA+ if the
  exception-propagation case warrants it).
- Implementation, including the priority-aware batched submit to the
  scheduler → **engineer**.
- Measurement: are call sites actually adopting the DSL after merge,
  or sticking with raw `add_node`? → **Curie**. Adoption is the
  empirical test of whether the abstraction barrier is the right one.
