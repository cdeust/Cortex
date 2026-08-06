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
# UNKNOWN      no tool attribution available. Treated as trusted-for-bypass so
#              that adding this parameter changes no existing caller's
#              behaviour; every untrusted channel reaches the gate through the
#              classification table below, never through this default.
ORIGIN_DELIBERATE = "deliberate"
ORIGIN_LOCAL_ACTION = "local_action"
ORIGIN_NETWORK = "network"
ORIGIN_UNKNOWN = "unknown"

ALL_ORIGINS: tuple[str, ...] = (
    ORIGIN_DELIBERATE,
    ORIGIN_LOCAL_ACTION,
    ORIGIN_NETWORK,
    ORIGIN_UNKNOWN,
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

# Content-derived write-gate bypasses are refused for these origins. Only
# NETWORK today; the set exists so the refusal is a data decision rather than
# an `if origin == "network"` scattered across call sites (§1.2).
_ORIGINS_REFUSED_CONTENT_BYPASS: frozenset[str] = frozenset({ORIGIN_NETWORK})


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

    Pre: ``origin`` is any string (an unrecognised value is treated as
    unknown).
    Post: False exactly for the origins in
    ``_ORIGINS_REFUSED_CONTENT_BYPASS``; True otherwise.

    The asymmetry is deliberate. ``force`` and a ``deliberate`` write class are
    out-of-band signals a human supplied, so they remain valid regardless of
    origin; ``bypass_error`` / ``bypass_decision`` are read out of the content
    itself, so they are exactly what an attacker would forge.
    """
    return origin not in _ORIGINS_REFUSED_CONTENT_BYPASS


def is_network_origin(origin: str) -> bool:
    """True when ``origin`` denotes content fetched from off this machine."""
    return origin == ORIGIN_NETWORK
