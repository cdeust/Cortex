"""Goal / task-set maintenance (A3) — a sustained goal vector that biases
processing toward goal-relevant information.

Cortex already has a *prospective* memory model (``core.prospective``): future-
oriented triggers ("remember to do X when Y happens") that fire, one-shot, when
the current context matches a trigger condition. That is a momentary,
event-driven check — a trigger either matches the current write/recall context
or it doesn't, and nothing carries the *task the agent is currently pursuing*
forward across operations to bias what gets stored and what surfaces. There is
no held task-set: each write and each recall is scored as if no goal were in
play.

This module adds that missing layer. It promotes the prospective trigger
representation into a *sustained goal vector* — a keyword / entity / directory
set assembled from the currently-active prospective triggers (or an explicit
current-task description) — and exposes a goal-relevance score for a candidate
memory plus small multiplicative re-weight factors for the write gate and the
recall fusion. While a goal is active, goal-relevant inputs are favored at the
gate and goal-relevant memories surface slightly ahead of equally-relevant but
off-task ones. When no goal is active the goal vector is empty and every factor
is exactly 1.0 — the write and recall paths are unchanged.

Neuroscience basis (DOI verified against Crossref):
  - Miller & Cohen (2001), "An Integrative Theory of Prefrontal Cortex
    Function," Annual Review of Neuroscience 24:167-202
    (doi:10.1146/annurev.neuro.24.1.167). The prefrontal cortex holds an active
    representation of the current goal / task-set and uses it to bias
    processing in posterior and limbic regions toward goal-relevant
    information — a sustained top-down signal, distinct from the stimulus that
    momentarily triggers a response. (This is the SAME reference A2 conflict
    monitoring cites for the control side; here we implement its
    goal-maintenance / task-set side.)

Design (pure business logic — no I/O). A ``GoalVector`` holds three feature
families lifted directly from the prospective trigger schema
(``trigger_condition`` keywords, ``entity_match`` entities, ``directory_match``
targets):

  keywords     — lowercased content tokens the active task is about (the same
                 word-boundary keyword surface ``prospective.check_trigger``
                 matches on for ``keyword_match``).
  entities     — named entities the task concerns (``entity_match``).
  directories  — working-directory fragments the task is scoped to
                 (``directory_match``).

``goal_relevance(goal, content, entities, directory)`` scores a candidate in
[0, 1] as the max of its keyword overlap, entity overlap, and directory match
against the active goal — how well the item matches the held task-set. The two
re-weight helpers turn that score into a bounded upward nudge
``1 + weight·relevance`` (relevance 0 → factor 1.0 → unchanged; higher
relevance → a small boost), mirroring the multiplicative shape of B2's
``value_learning.retrieval_priority`` rather than an RRF rank blend.

Honesty note (zetetic standard, matching value_learning.py /
source_monitoring.py / attentional_control.py): **this is a DESIGN INFERENCE,
not a claim about the brain.** Miller & Cohen describe a *learned*, sustained
PFC activity pattern that gates posterior processing; what this module
implements is a deterministic keyword/entity/directory goal-match re-weight
promoted from the existing prospective-trigger surface. There is no learned
task-set controller, no trained gating weights, and no embedding here — the
relevance is lexical/feature overlap (the caller may substitute a precomputed
semantic score). The paper motivates the *shape* of the design (a persistent
goal representation biases downstream selection); it does not license calling
this a model of prefrontal task-set maintenance. The re-weight is deliberately
small so a strong content match is never overridden by goal relevance, and the
empty-goal case is a strict identity so the mechanism is behavior-preserving by
default.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ── Tuning constants ─────────────────────────────────────────────────────────
# Multiplicative nudge weight for the write gate. A fully goal-relevant input
# (relevance 1.0) has its novelty scaled by 1 + GOAL_WRITE_WEIGHT; an off-task
# input (relevance 0.0) is unchanged. Small by design — goal relevance favors
# goal-relevant inputs, it does not force storage of them. Fixed engineering
# constant, not learned.
GOAL_WRITE_WEIGHT: float = 0.15

# Multiplicative nudge weight for the recall fusion score. Same shape and
# rationale as GOAL_WRITE_WEIGHT and the same magnitude as B2's value_priority
# weight (value_learning.retrieval_priority default 0.15) so goal relevance
# refines rather than reorders content relevance.
GOAL_RECALL_WEIGHT: float = 0.15

# Minimum token length kept when deriving goal keywords, matching the
# prospective extractor's own ``len(w) > 2`` filter so the goal surface stays
# consistent with the triggers it is promoted from.
_MIN_KEYWORD_LEN: int = 3

# Stop words dropped from goal keywords — the same short closed-class set
# prospective.py excludes when it builds trigger_condition keywords, so a goal
# promoted from a trigger and the trigger itself share a vocabulary.
_STOP_WORDS = frozenset({"the", "and", "for", "with", "that", "this", "from"})

_WORD_RE = re.compile(r"[a-z0-9]+")


# ── Goal vector ──────────────────────────────────────────────────────────────
@dataclass
class GoalVector:
    """A sustained goal / task-set representation (A3).

    Three feature families lifted from the prospective trigger schema:

    ``keywords``     — lowercased content tokens the active task is about.
    ``entities``     — lowercased named entities the task concerns.
    ``directories``  — lowercased working-directory fragments the task is
                       scoped to.

    An empty vector (no keywords, entities, or directories) is *inactive*:
    every relevance score is 0.0 and every re-weight factor is 1.0, so the
    write and recall paths behave exactly as they do with no goal. This is the
    behavior-preserving default.
    """

    keywords: frozenset[str] = field(default_factory=frozenset)
    entities: frozenset[str] = field(default_factory=frozenset)
    directories: tuple[str, ...] = ()
    label: str = ""


def goal_vector_is_active(goal: "GoalVector") -> bool:
    """True iff the goal carries any keyword, entity, or directory signal.

    A free function, not a method: mutmut categorically excludes the body of
    any `@dataclass`-decorated class (`mutmut/mutation/file_mutation.py:236`),
    so logic placed on ``GoalVector`` methods would carry zero mutation
    coverage no matter how the test loader names the module (issue #262 3rd
    pass; issue #282).
    """
    return bool(goal.keywords or goal.entities or goal.directories)


def goal_vector_as_dict(goal: "GoalVector") -> dict:
    return {
        "label": goal.label,
        "keywords": sorted(goal.keywords),
        "entities": sorted(goal.entities),
        "directories": list(goal.directories),
        "is_active": goal_vector_is_active(goal),
    }


# The canonical inactive goal — a module-level singleton the caller can use when
# no task is in play. Sharing one instance makes the "no active goal" identity
# path allocation-free.
EMPTY_GOAL = GoalVector()


def _tokenize(text: str) -> list[str]:
    """Lowercase word-boundary tokens, filtered like the prospective extractor."""
    return [
        w
        for w in _WORD_RE.findall(text.lower())
        if len(w) >= _MIN_KEYWORD_LEN and w not in _STOP_WORDS
    ]


def build_goal_from_triggers(
    triggers: list[dict] | None,
    *,
    label: str = "",
) -> GoalVector:
    """Promote a set of active prospective triggers into a sustained goal vector.

    Consumes the SAME trigger dicts ``core.prospective`` produces and stores
    ({``trigger_type``, ``trigger_condition``, optional ``target_directory``}).
    Each contributes to the goal by its type:

      - ``keyword_match``   → its condition tokens join the goal keywords.
      - ``entity_match``    → its condition (a single entity name) joins the
                              goal entities.
      - ``directory_match`` → its ``target_directory`` (or condition) joins the
                              goal directories.
      - ``time_based``      → contributes nothing to the goal surface (a clock
                              condition is not a content/task signal).

    An empty or None trigger list yields ``EMPTY_GOAL`` (inactive). This is the
    promotion step A3 is built on: prospective triggers are momentary,
    event-driven checks; the goal vector holds their content forward as the
    task-set that biases subsequent writes and recalls while it is active.
    """
    if not triggers:
        return EMPTY_GOAL

    keywords: set[str] = set()
    entities: set[str] = set()
    directories: list[str] = []

    for trig in triggers:
        ttype = trig.get("trigger_type", "")
        condition = (trig.get("trigger_condition") or "").strip()
        if ttype == "keyword_match":
            keywords.update(_tokenize(condition))
        elif ttype == "entity_match":
            if condition:
                entities.add(condition.lower())
        elif ttype == "directory_match":
            target = (trig.get("target_directory") or condition).strip().lower()
            if target:
                directories.append(target)
        # time_based and unknown types contribute no task-content signal.

    if not (keywords or entities or directories):
        return EMPTY_GOAL

    return GoalVector(
        keywords=frozenset(keywords),
        entities=frozenset(entities),
        directories=tuple(directories),
        label=label,
    )


def build_goal_from_task(
    task: str,
    *,
    entities: list[str] | None = None,
    directory: str = "",
    label: str = "",
) -> GoalVector:
    """Build a goal vector directly from an explicit current-task description.

    A convenience alternative to ``build_goal_from_triggers`` for callers that
    already know the current task (e.g. an agent-supplied focus string) rather
    than harvesting it from stored prospective triggers. The task text is
    tokenized into keywords with the same filter; ``entities`` and ``directory``
    populate the other two families. An empty task with no entities/directory
    yields ``EMPTY_GOAL``.
    """
    keywords = frozenset(_tokenize(task or ""))
    ents = frozenset(e.lower() for e in (entities or []) if e)
    dirs = (directory.strip().lower(),) if directory.strip() else ()
    if not (keywords or ents or dirs):
        return EMPTY_GOAL
    return GoalVector(
        keywords=keywords,
        entities=ents,
        directories=dirs,
        label=label or (task.strip() if task else ""),
    )


# ── Goal relevance ───────────────────────────────────────────────────────────
def _keyword_overlap(goal_keywords: frozenset[str], content: str) -> float:
    """Fraction of goal keywords present (word-boundary) in the content."""
    if not goal_keywords:
        return 0.0
    content_tokens = set(_WORD_RE.findall(content.lower()))
    if not content_tokens:
        return 0.0
    hit = sum(1 for kw in goal_keywords if kw in content_tokens)
    return hit / len(goal_keywords)


def _entity_overlap(goal_entities: frozenset[str], entities: list[str] | None) -> float:
    """Fraction of goal entities present in the candidate's entity list."""
    if not goal_entities:
        return 0.0
    cand = {e.lower() for e in (entities or []) if e}
    if not cand:
        return 0.0
    hit = sum(1 for ge in goal_entities if ge in cand)
    return hit / len(goal_entities)


def _directory_match(goal_directories: tuple[str, ...], directory: str) -> float:
    """1.0 iff the candidate's directory falls under any goal directory."""
    if not goal_directories or not directory:
        return 0.0
    d = directory.lower()
    return 1.0 if any(gd and gd in d for gd in goal_directories) else 0.0


def goal_relevance(
    goal: GoalVector,
    content: str,
    *,
    entities: list[str] | None = None,
    directory: str = "",
) -> float:
    """Score how well a candidate matches the active goal, in [0, 1].

    The score is the MAX of the three feature-family overlaps (keyword, entity,
    directory) — a candidate is goal-relevant if it matches the task on *any*
    axis, and matching on several does not inflate it past 1.0. An inactive
    goal (``EMPTY_GOAL`` / no signal) scores every candidate 0.0, which drives
    the re-weight factors below to the identity 1.0.

    Relevance here is lexical / feature overlap; a caller with a semantic
    similarity between the goal and the candidate may pass it through the
    re-weight helpers instead (see honesty note in the module docstring).
    """
    if not goal_vector_is_active(goal):
        return 0.0
    kw = _keyword_overlap(goal.keywords, content)
    ent = _entity_overlap(goal.entities, entities)
    d = _directory_match(goal.directories, directory)
    return max(kw, ent, d)


# ── Re-weight helpers (the multiplicative nudge) ─────────────────────────────
def goal_write_gain(
    goal: GoalVector,
    content: str,
    *,
    entities: list[str] | None = None,
    directory: str = "",
    weight: float = GOAL_WRITE_WEIGHT,
) -> float:
    """Write-gate gain in [1.0, 1.0 + weight] for a candidate input.

    ``gain = 1 + weight·goal_relevance``. An off-task input (relevance 0) or an
    inactive goal returns exactly 1.0 — the gate's novelty is unchanged. A
    goal-relevant input is favored by a small boost. The caller multiplies its
    novelty score by this gain, so goal-relevant inputs clear the write
    threshold slightly more easily while the goal is active.
    """
    if not goal_vector_is_active(goal):
        return 1.0
    rel = goal_relevance(goal, content, entities=entities, directory=directory)
    return 1.0 + weight * rel


def goal_recall_multiplier(
    goal: GoalVector,
    content: str,
    *,
    entities: list[str] | None = None,
    directory: str = "",
    weight: float = GOAL_RECALL_WEIGHT,
) -> float:
    """Recall-score multiplier in [1.0, 1.0 + weight] for a candidate memory.

    Same shape as ``goal_write_gain`` — ``1 + weight·goal_relevance`` — applied
    to a retrieved candidate's content-relevance score so goal-relevant
    memories surface slightly ahead of equally-relevant off-task ones while the
    goal is active. Inactive goal or zero relevance → 1.0 (identity), so recall
    ordering is unchanged by default.
    """
    if not goal_vector_is_active(goal):
        return 1.0
    rel = goal_relevance(goal, content, entities=entities, directory=directory)
    return 1.0 + weight * rel
