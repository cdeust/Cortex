"""Procedural memory — skills learned as recurring successful action sequences.

Cortex is otherwise a *declarative* memory system (episodic events + semantic
knowledge, retrieved by content similarity). This module adds the missing
*non-declarative* system: procedural memory, the basal-ganglia analog that
stores **how to act** rather than **what is true**, and is retrieved by
*situation* rather than by content.

Neuroscience basis (all three DOIs verified against Crossref: authors, title,
journal, volume, pages, year confirmed):
  - Graybiel (2008), "Habits, rituals, and the evaluative brain," Annu. Rev.
    Neurosci. 31:359-387 (doi:10.1146/annurev.neuro.29.051605.112851). The
    basal ganglia *chunk* repeated action sequences into unified habit units;
    a behaviour becomes habitual only after repetition. Here: recurring
    contiguous tool-use subsequences are mined into skill "chunks," and a skill
    graduates from goal-directed to habitual after a repetition threshold.
  - Doya (2000), "Complementary roles of basal ganglia and cerebellum in
    learning and motor control," Curr. Opin. Neurobiol. 10:732-739
    (doi:10.1016/S0959-4388(00)00153-7). The basal ganglia implement
    reinforcement learning, distinct from declarative memory.
  - Schultz, Dayan & Montague (1997), "A neural substrate of prediction and
    reward," Science 275:1593-1599 (doi:10.1126/science.275.5306.1593).
    Dopamine encodes a reward-prediction error. Here: each execution of a skill
    carries an outcome (success / failure); proficiency is a reinforced running
    success rate — the reward signal that strengthens or weakens the habit.

Scope / honesty note (zetetic standard, matching dual_store_cls.py): this is a
frequent-subsequence miner plus a reinforced success-rate estimator. It is
*conceptually aligned* with basal-ganglia chunking and RL, but the mechanism is
sequence mining and running averages, not a neural actor-critic. The papers
motivate the design; they are not implemented as computational models.

Boundary with declarative memory: procedural skills are stored with
``store_type='procedural'`` (the memories table's ``store_type`` column is free
text, already indexed — no schema migration) and are retrieved by
``match_skills`` against the *current situation* (domain, directory, recent
tools), never by embedding similarity to content. That situational-vs-content
retrieval split is the defining distinction from episodic/semantic memory.

Pure business logic — no I/O. Handlers pass in already-fetched session
evidence (the same ``tools_used`` that ``auto_task_record`` already collects)
and persist the returned skill records.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone

# ── Tuning constants ────────────────────────────────────────────────────────
# Minimum number of distinct sessions a subsequence must appear in to count as
# a recurring skill (frequent-subsequence support). Below this it is treated as
# incidental, not a habit.
MIN_SKILL_SUPPORT: int = 3

# Chunk length bounds. A skill is a contiguous action subsequence of length in
# [MIN, MAX]. Single actions are not skills; very long chains are rarely
# reproducible verbatim.
MIN_SKILL_LEN: int = 2
MAX_SKILL_LEN: int = 6

# Repetitions of successful execution after which a goal-directed skill is
# considered *habitual* (Graybiel: habits form with repetition). Purely a
# label / retrieval-priority threshold; it does not gate execution.
HABITUAL_THRESHOLD: int = 5

# Reinforcement learning rate for the proficiency running-average update
# (Rescorla-Wagner / TD style: p <- p + alpha * (reward - p)). Small so a
# single bad run doesn't erase an established habit.
PROFICIENCY_ALPHA: float = 0.2

# Laplace smoothing prior for the initial proficiency estimate, so a skill seen
# once successfully doesn't read as certain.
_PRIOR_SUCCESS: float = 1.0
_PRIOR_TOTAL: float = 2.0

# Reward at or above this counts a run as a success.
# source: pre-existing tuned value, extracted unchanged (#197 family 3);
# provenance not recorded at introduction
_SUCCESS_REWARD: float = 0.5

# Context-similarity score at or above this counts as a context match.
# source: pre-existing tuned value, extracted unchanged (#197 family 3);
# provenance not recorded at introduction
_CONTEXT_MATCH_THRESHOLD: float = 0.5


# ── Data model ──────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class ActionStep:
    """One normalized action in a procedure.

    ``tool`` is the tool/verb name (e.g. ``"edit_file"``). ``target_kind`` is an
    optional coarse object class (e.g. ``"test"``, ``"config"``) so a skill can
    generalize across specific files while still distinguishing "edit a test"
    from "edit a config". ``None`` means unspecified / any target.
    """

    tool: str
    target_kind: str | None = None

    def key(self) -> str:
        return (
            self.tool if self.target_kind is None else f"{self.tool}:{self.target_kind}"
        )


@dataclass
class ProceduralSkill:
    """A learned procedure: a recurring action sequence with a success record.

    Persistence maps onto the memories table (``store_type='procedural'``):
      - ``occurrences``      -> access_count
      - ``success_count``    -> useful_count
      - ``proficiency``      -> a reinforced running success rate (see update)
      - ``is_habitual``      -> consolidation_stage graduation (label only)
    The record is content-addressed by ``skill_id`` (a hash of the action
    sequence) so the same procedure mined in different sessions merges rather
    than duplicating.
    """

    sequence: tuple[ActionStep, ...]
    context_signature: str = ""
    occurrences: int = 0  # times this sequence has been observed
    success_count: int = 0  # observations whose session outcome was good
    failure_count: int = 0
    proficiency: float = 0.0  # reinforced running success rate in [0, 1]
    last_seen: str = ""  # ISO timestamp of most recent observation
    skill_id: str = ""

    def __post_init__(self) -> None:
        if not self.skill_id:
            self.skill_id = skill_id_for(self.sequence)

    @property
    def is_habitual(self) -> bool:
        """A skill is habitual once it has enough *successful* repetitions."""
        return self.success_count >= HABITUAL_THRESHOLD

    @property
    def length(self) -> int:
        return len(self.sequence)

    def as_dict(self) -> dict:
        return {
            "skill_id": self.skill_id,
            "sequence": [s.key() for s in self.sequence],
            "context_signature": self.context_signature,
            "occurrences": self.occurrences,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "proficiency": round(self.proficiency, 4),
            "is_habitual": self.is_habitual,
            "last_seen": self.last_seen,
        }


def skill_id_for(sequence: tuple[ActionStep, ...]) -> str:
    """Stable content hash of an action sequence (12 hex chars)."""
    joined = ">".join(s.key() for s in sequence)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:12]


# ── Action normalization ────────────────────────────────────────────────────
# Coarse target-kind inference from a tool-call target string. Keeps skills
# general ("edit a test") without exploding on specific paths.
_TARGET_KIND_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"test|spec|_test\.|\.test\.", re.IGNORECASE), "test"),
    (
        re.compile(r"\.(ya?ml|toml|ini|cfg|conf|json)$|config|settings", re.IGNORECASE),
        "config",
    ),
    (re.compile(r"readme|\.md$|docs?/", re.IGNORECASE), "doc"),
    (re.compile(r"\.sql$|schema|migration", re.IGNORECASE), "schema"),
    (re.compile(r"\.(py|js|ts|go|rs|java|rb|c|cpp|h)$", re.IGNORECASE), "code"),
]


def infer_target_kind(target: str | None) -> str | None:
    """Map a concrete target (path/arg) to a coarse object class, or None."""
    if not target:
        return None
    for pattern, kind in _TARGET_KIND_PATTERNS:
        if pattern.search(target):
            return kind
    return None


def normalize_actions(
    tool_calls: list[dict] | list[str],
) -> list[ActionStep]:
    """Turn a session's raw tool usage into a normalized action sequence.

    Accepts either the rich form (list of ``{"tool": str, "target": str}``
    dicts — as available from tool-call logs) or the lightweight form (list of
    tool-name strings, as ``auto_task_record`` already collects in
    ``tools_used``). Consecutive identical actions are collapsed to a single
    step (a run of three ``read_file`` calls is one "read" action in the
    procedure), matching how habits chunk repeated sub-actions.
    """
    steps: list[ActionStep] = []
    for call in tool_calls:
        if isinstance(call, str):
            step = ActionStep(tool=call, target_kind=None)
        else:
            step = ActionStep(
                tool=call.get("tool", "") or "",
                target_kind=infer_target_kind(call.get("target")),
            )
        if not step.tool:
            continue
        if steps and steps[-1].key() == step.key():
            continue  # collapse consecutive duplicates
        steps.append(step)
    return steps


# ── Chunking / frequent-subsequence mining (Graybiel) ───────────────────────
def _contiguous_subsequences(
    seq: list[ActionStep], min_len: int, max_len: int
) -> list[tuple[ActionStep, ...]]:
    """All contiguous windows of length in [min_len, max_len]."""
    out: list[tuple[ActionStep, ...]] = []
    n = len(seq)
    for length in range(min_len, min(max_len, n) + 1):
        for start in range(0, n - length + 1):
            out.append(tuple(seq[start : start + length]))
    return out


def mine_skills(
    sessions: list[dict],
    *,
    min_support: int = MIN_SKILL_SUPPORT,
    min_len: int = MIN_SKILL_LEN,
    max_len: int = MAX_SKILL_LEN,
) -> list[ProceduralSkill]:
    """Mine recurring successful action sequences into skill chunks.

    Each session dict provides:
      - ``tools_used`` / ``tool_calls``: the action evidence (either form
        accepted by ``normalize_actions``).
      - ``outcome``: ``"success"`` | ``"failure"`` (or a bool / float in [0,1]);
        the session-level reward. Missing outcome is treated as neutral and does
        not count toward success or failure.
      - ``domain`` / ``cwd`` (optional): used to build the context signature.

    A candidate sequence becomes a skill when it appears (contiguously) in at
    least ``min_support`` distinct sessions. Its ``success_count`` /
    ``failure_count`` aggregate the outcomes of the sessions it appeared in, and
    ``proficiency`` is the smoothed success rate. Skills are returned sorted by
    a combined support x proficiency priority, strongest first.
    """
    # skill_id -> aggregate accumulator
    acc: dict[str, dict] = {}

    for session in sessions:
        raw = session.get("tool_calls") or session.get("tools_used") or []
        actions = normalize_actions(raw)
        if len(actions) < min_len:
            continue
        reward = _outcome_to_reward(session.get("outcome"))
        ctx = context_signature(session)
        seen_ids: set[str] = set()
        for sub in _contiguous_subsequences(actions, min_len, max_len):
            sid = skill_id_for(sub)
            if sid in seen_ids:
                continue  # count a sequence once per session (session support)
            seen_ids.add(sid)
            slot = acc.setdefault(
                sid,
                {
                    "sequence": sub,
                    "sessions": 0,
                    "succ": 0,
                    "fail": 0,
                    "contexts": {},
                    "last_seen": "",
                },
            )
            slot["sessions"] += 1
            if reward is not None:
                if reward >= _SUCCESS_REWARD:
                    slot["succ"] += 1
                else:
                    slot["fail"] += 1
            if ctx:
                slot["contexts"][ctx] = slot["contexts"].get(ctx, 0) + 1
            ts = session.get("timestamp") or session.get("ended_at") or ""
            if ts > slot["last_seen"]:
                slot["last_seen"] = ts

    skills: list[ProceduralSkill] = []
    for sid, slot in acc.items():
        if slot["sessions"] < min_support:
            continue
        succ, fail = slot["succ"], slot["fail"]
        proficiency = (succ + _PRIOR_SUCCESS) / (succ + fail + _PRIOR_TOTAL)
        dominant_ctx = (
            max(slot["contexts"].items(), key=lambda kv: kv[1])[0]
            if slot["contexts"]
            else ""
        )
        skills.append(
            ProceduralSkill(
                sequence=slot["sequence"],
                context_signature=dominant_ctx,
                occurrences=slot["sessions"],
                success_count=succ,
                failure_count=fail,
                proficiency=proficiency,
                last_seen=slot["last_seen"],
                skill_id=sid,
            )
        )

    skills.sort(key=lambda s: _skill_priority(s), reverse=True)
    return skills


def _skill_priority(skill: ProceduralSkill) -> float:
    """Retrieval priority: reinforced proficiency x log-support x length bonus.

    Longer chunks that recur and succeed are the most valuable procedures;
    support is dampened (log) so a very common 2-step pair doesn't dominate a
    reliable 5-step routine.
    """
    import math

    support = math.log1p(skill.occurrences)
    length_bonus = 1.0 + 0.1 * (skill.length - MIN_SKILL_LEN)
    return skill.proficiency * support * length_bonus


# ── Reinforcement / proficiency update (Doya, Schultz) ──────────────────────
def _outcome_to_reward(outcome) -> float | None:
    """Normalize a session outcome to a reward in [0,1], or None if unknown."""
    if outcome is None:
        return None
    if isinstance(outcome, bool):
        return 1.0 if outcome else 0.0
    if isinstance(outcome, (int, float)):
        return max(0.0, min(1.0, float(outcome)))
    if isinstance(outcome, str):
        o = outcome.strip().lower()
        if o in {"success", "ok", "pass", "passed", "good"}:
            return 1.0
        if o in {"failure", "fail", "failed", "error", "bad"}:
            return 0.0
    return None


def reinforce(skill: ProceduralSkill, outcome) -> ProceduralSkill:
    """Apply one execution outcome to a skill (the RPE-style update).

    ``proficiency <- proficiency + alpha * (reward - proficiency)`` — a
    delta-rule / TD(0) update where ``reward - proficiency`` is the
    reward-prediction error (Schultz 1997). Success and failure counters and
    occurrence count are advanced. Returns a new updated skill (skills are
    treated as values; the caller persists the result).
    """
    reward = _outcome_to_reward(outcome)
    occurrences = skill.occurrences + 1
    success_count = skill.success_count
    failure_count = skill.failure_count
    proficiency = skill.proficiency
    if reward is not None:
        # On the very first observation, seed from the smoothed prior instead of
        # from 0 so a first success lands at a sensible level.
        if skill.occurrences == 0 and proficiency == 0.0:
            proficiency = _PRIOR_SUCCESS / _PRIOR_TOTAL
        proficiency = proficiency + PROFICIENCY_ALPHA * (reward - proficiency)
        proficiency = max(0.0, min(1.0, proficiency))
        if reward >= _SUCCESS_REWARD:
            success_count += 1
        else:
            failure_count += 1
    return ProceduralSkill(
        sequence=skill.sequence,
        context_signature=skill.context_signature,
        occurrences=occurrences,
        success_count=success_count,
        failure_count=failure_count,
        proficiency=proficiency,
        last_seen=datetime.now(timezone.utc).isoformat(),
        skill_id=skill.skill_id,
    )


# ── Context signature + situational retrieval ───────────────────────────────
def context_signature(session: dict) -> str:
    """Compact signature of the situation a procedure was used in.

    Built from domain + the leaf directory of cwd. This is the retrieval key
    for procedural memory — procedures are recalled by *situation*, not by
    content similarity.
    """
    domain = (session.get("domain") or "").strip().lower()
    cwd = (session.get("cwd") or "").strip()
    leaf = ""
    if cwd:
        leaf = re.split(r"[\\/]", cwd.rstrip("/\\"))[-1].lower()
    parts = [p for p in (domain, leaf) if p]
    return "|".join(parts)


def match_skills(
    current_context: dict,
    skills: list[ProceduralSkill],
    *,
    top_k: int = 5,
    min_proficiency: float = 0.5,
) -> list[dict]:
    """Retrieve applicable procedures for the current situation.

    Scores each stored skill by context overlap x proficiency x support, filters
    out unreliable skills (proficiency below ``min_proficiency``), and returns
    the top ``top_k`` as ``{skill, score, why}`` dicts. This is procedural
    *recall*: "in this situation, the routine that usually works is X."
    """
    target = context_signature(current_context)
    target_tokens = set(target.split("|")) if target else set()
    recent = normalize_actions(
        current_context.get("tool_calls") or current_context.get("tools_used") or []
    )
    recent_keys = {s.key() for s in recent}

    scored: list[dict] = []
    for skill in skills:
        if skill.proficiency < min_proficiency:
            continue
        skill_tokens = (
            set(skill.context_signature.split("|"))
            if skill.context_signature
            else set()
        )
        # Context overlap (Jaccard); 0.5 baseline when the skill is context-free
        # so a globally useful routine can still surface.
        if skill_tokens and target_tokens:
            inter = len(skill_tokens & target_tokens)
            union = len(skill_tokens | target_tokens)
            ctx_score = inter / union if union else 0.0
        else:
            ctx_score = 0.3
        # Small bonus if the procedure's opening action matches what the agent
        # just did (the habit is "primed" by the current action).
        prime = 0.0
        if recent_keys and skill.sequence and skill.sequence[0].key() in recent_keys:
            prime = 0.15
        score = (ctx_score + prime) * _skill_priority(skill)
        if score <= 0.0:
            continue
        why = _explain_match(skill, ctx_score, prime)
        scored.append({"skill": skill.as_dict(), "score": round(score, 4), "why": why})

    scored.sort(key=lambda d: d["score"], reverse=True)
    return scored[:top_k]


def _explain_match(skill: ProceduralSkill, ctx_score: float, prime: float) -> str:
    bits = [
        f"{skill.length}-step routine",
        f"{skill.proficiency:.0%} success over {skill.occurrences} uses",
    ]
    if skill.is_habitual:
        bits.append("habitual")
    if ctx_score >= _CONTEXT_MATCH_THRESHOLD:
        bits.append(f"matches context '{skill.context_signature}'")
    if prime:
        bits.append("primed by current action")
    return "; ".join(bits)
