"""Capture origin — which CHANNEL produced a memory's content (issue #365).

Pure business logic, zero I/O, stdlib only.

This module answers one question: did this content come from the user, from
this machine, or from off-machine? It answers it from the **tool that produced
the content**, which is known out-of-band at capture time and cannot be
influenced by the content itself.

That last property is the whole point, and it is why this is a third concept
rather than a reuse of either neighbour:

  - ``core/provenance.py`` grades **reference verifiability** — do this
    memory's file paths, commit SHAs, URLs and artifact digests still check
    out? Its vocabulary (verified / verifiable / unverifiable) is derived by
    reading the content's references.
  - ``core/source_monitoring.py`` attributes **epistemic origin** — was this
    perceived, told, or inferred? (Johnson & Raye 1981.) Its vocabulary is
    derived by regex over the content's own wording and grounding markers.

Both are useful and neither can carry a security property, because in both
the attacker supplies the input to the classifier. A hostile web page dense
with file paths and URLs grades ``verified`` and classifies ``perceived`` —
the most credible value in each vocabulary. Origin has to be decided by the
channel, upstream of anything the content can say about itself.

Why it matters (issue #365): ``hooks/post_tool_capture`` auto-captures tool
output into long-term memory, and ``hooks/session_start`` replays stored
memories verbatim into later sessions. Content arriving from the network is
therefore a write into durable, cross-session state. The write gate offers
content-derived bypasses (``bypass_error`` / ``bypass_decision``, via
``core/thermodynamics``) which let text that merely *looks* like an error or a
decision skip the novelty REJECT. Fetched text must not be able to buy that
bypass by shaping itself, so the gate consults ``may_bypass_write_gate_on_content``.

The vocabulary is deliberately coarse. Three values is enough to express the
only distinction the gate needs — is this content from off-machine — and a
coarse table is auditable at a glance, which a per-tool trust score would not
be.
"""

from __future__ import annotations

# ── Vocabulary ─────────────────────────────────────────────────────────────
# DELIBERATE   the user asked for this in so many words (an explicit
#              `remember` / `wiki_write`). Highest trust: a human chose it.
# LOCAL_ACTION the agent's own tool acting on this machine (Edit, Write,
#              Bash, Read, Glob, Grep, NotebookEdit/Read). First-party but
#              machine-generated: trusted as to ORIGIN, which says nothing
#              about whether its claims are correct.
# NETWORK      content that came from off-machine (WebFetch, WebSearch).
#              Third-party and attacker-influenceable.
# UNKNOWN      no tool attribution available, or a tool nobody has classified.
#              REFUSED the content-derived bypass. This is the fail-closed
#              choice: an unclassified channel might be off-machine, and the
#              cost of being wrong is a rejected write rather than a hostile
#              page installing itself into durable memory. A caller that
#              legitimately needs the bypass says which channel it is.
# LEGACY       written before this attribute existed. NOT the same claim as
#              UNKNOWN: unknown means a channel produced this and nobody
#              classified it, legacy means no channel was ever recorded
#              because the column did not exist yet. Set once, by the
#              migration that adds the column, to every row present at that
#              instant (issue #368) — never by the write path, which always
#              knows one of the four values above.
ORIGIN_DELIBERATE = "deliberate"
ORIGIN_LOCAL_ACTION = "local_action"
ORIGIN_NETWORK = "network"
ORIGIN_UNKNOWN = "unknown"
ORIGIN_LEGACY = "legacy"

ALL_ORIGINS: tuple[str, ...] = (
    ORIGIN_DELIBERATE,
    ORIGIN_LOCAL_ACTION,
    ORIGIN_NETWORK,
    ORIGIN_UNKNOWN,
    ORIGIN_LEGACY,
)

# Tools whose output originates off this machine. Lower-cased for comparison
# because Claude Code tool names are CamelCase at the hook boundary.
# Kept as an explicit set, not a heuristic: a tool is untrusted because we
# decided it is, and adding one must be a visible edit here.
_NETWORK_TOOLS: frozenset[str] = frozenset({"webfetch", "websearch"})

# Tools that act on this machine. Enumerated rather than treated as "everything
# not in _NETWORK_TOOLS" so that a tool nobody has classified yet lands in
# UNKNOWN and shows up as unclassified, instead of being silently promoted to
# first-party.
_LOCAL_ACTION_TOOLS: frozenset[str] = frozenset(
    {
        "edit",
        "write",
        "multiedit",
        "notebookedit",
        "notebookread",
        "bash",
        "read",
        "glob",
        "grep",
    }
)

# Origins ALLOWED to claim a content-derived write-gate bypass. An allowlist,
# not a denylist of untrusted origins, so the control fails closed.
#
# A denylist here would be fail-open in exactly the case this module exists to
# defend. `_NETWORK_TOOLS` hardcodes two names against a host whose tool
# surface changes: add a third off-machine tool, or rename one, and its content
# classifies UNKNOWN. Under a denylist of {NETWORK} that silently regains the
# bypass — the control stops applying with no failing test and no signal, which
# is the same shape as the issue this module closes. Under an allowlist an
# unclassified origin is simply refused, and the cost of a missing
# classification is a rejected write rather than a trusted one.
_ORIGINS_ALLOWED_CONTENT_BYPASS: frozenset[str] = frozenset(
    {ORIGIN_DELIBERATE, ORIGIN_LOCAL_ACTION}
)

# Origins that keep FULL RANKING WEIGHT at read time (issue #368). An
# allowlist for the same reason as the one above: the read side must fail
# closed too. A newly added off-machine tool classifies UNKNOWN, and under a
# denylist of {NETWORK} it would silently keep full weight — the control
# would stop applying with no failing test, which is the shape of the bug
# #365 closed on the write side.
#
# LEGACY is trusted here and nowhere else. Those rows predate the attribute,
# so they cannot be attributed; demoting them would re-rank the entire
# historical corpus at migration time on no evidence. They are also, by
# construction, unreachable by an attacker acting after the migration — the
# value is written once, by the migration, and never by the write path.
_ORIGINS_TRUSTED_AT_READ: frozenset[str] = frozenset(
    {ORIGIN_DELIBERATE, ORIGIN_LOCAL_ACTION, ORIGIN_LEGACY}
)


def classify_capture_origin(tool_name: str) -> str:
    """Map a producing tool name to its capture origin.

    Pre: ``tool_name`` is the tool name as reported at the hook boundary (any
    case); may be empty.
    Post: returns one of ``ALL_ORIGINS``. An empty or unrecognised tool name
    yields ``ORIGIN_UNKNOWN`` — never a guess, and never LOCAL_ACTION by
    default, so a newly added tool is visibly unclassified rather than
    silently trusted.

    Never inspects content: the argument is a tool name by construction.
    """
    # `or ""` is None-safety for .strip(); the empty string then simply matches
    # neither set and falls through to ORIGIN_UNKNOWN, so no separate
    # empty-input guard is needed. Documented equivalent mutant (§12.4): the
    # scoped mutation run replaces this literal with a non-empty one
    # ("XXXX"), which is unobservable — an unrecognised name and an empty name
    # both return ORIGIN_UNKNOWN, by construction of the two membership tests
    # below. No test can distinguish them, so this is equivalent rather than a
    # coverage gap.
    key = (tool_name or "").strip().lower()
    if key in _NETWORK_TOOLS:
        return ORIGIN_NETWORK
    if key in _LOCAL_ACTION_TOOLS:
        return ORIGIN_LOCAL_ACTION
    return ORIGIN_UNKNOWN


def may_bypass_write_gate_on_content(origin: str) -> bool:
    """Whether content from ``origin`` may claim a content-derived bypass.

    Pre: ``origin`` is any string.
    Post: True exactly for the origins in
    ``_ORIGINS_ALLOWED_CONTENT_BYPASS``; False otherwise, including for
    ``ORIGIN_UNKNOWN`` and for any value this module does not recognise.

    The asymmetry is deliberate. ``force`` and a ``deliberate`` write class are
    out-of-band signals a human supplied, so they remain valid regardless of
    origin; ``bypass_error`` / ``bypass_decision`` are read out of the content
    itself, so they are exactly what an attacker would forge.
    """
    return origin in _ORIGINS_ALLOWED_CONTENT_BYPASS


def is_network_origin(origin: str) -> bool:
    """True when ``origin`` denotes content fetched from off this machine."""
    return origin == ORIGIN_NETWORK


def is_trusted_at_read(origin: str) -> bool:
    """Whether ``origin`` keeps full ranking weight and may earn heat.

    Pre: ``origin`` is any string.
    Post: True exactly for ``_ORIGINS_TRUSTED_AT_READ``; False otherwise,
    including for ``ORIGIN_UNKNOWN`` and unrecognised values.

    The boolean the read path needs, stated once. Callers previously would
    have had to spell it ``trust_factor(origin, 0.0) == 0.0``, which reads as
    arithmetic and hides a policy question behind a sentinel value.
    """
    return origin in _ORIGINS_TRUSTED_AT_READ


def trust_factor(origin: str, untrusted_factor: float) -> float:
    """Ranking multiplier for content captured through ``origin``.

    Pre: ``origin`` is any string; ``untrusted_factor`` is the measured
    demotion weight (0 < w <= 1), supplied by the caller rather than fixed
    here — its value comes from a committed ablation sweep, not from this
    module.
    Post: returns 1.0 for origins in ``_ORIGINS_TRUSTED_AT_READ``, and
    ``untrusted_factor`` for every other value, including ``ORIGIN_UNKNOWN``
    and any string this module does not recognise.

    Multiplicative, not additive, and this is the load-bearing choice: an
    additive term cannot demote. At best it contributes zero, which leaves a
    hostile passage's similarity score untouched and still winning. A factor
    below 1 scales the whole fused score down, so a more-similar untrusted
    memory can be ordered below a less-similar trusted one — which is the
    property arXiv 2604.16548 requires and that retrieval-time filtering
    alone does not provide.
    """
    return 1.0 if origin in _ORIGINS_TRUSTED_AT_READ else untrusted_factor


def trusted_origins_at_read() -> tuple[str, ...]:
    """The origins that keep full ranking weight, for backends that filter
    server-side.

    Post: a sorted tuple, so the value is stable across processes — a
    frozenset's iteration order is not, and this tuple is embedded in a SQL
    parameter that shows up in query plans and logs.

    Exists so a store can be HANDED the policy instead of restating it.
    ``infrastructure`` may not import ``core``, so the alternative would be a
    second copy of the vocabulary living in SQL, free to drift from this one
    — the exact failure this module was written to prevent on the write side.
    """
    return tuple(sorted(_ORIGINS_TRUSTED_AT_READ))
