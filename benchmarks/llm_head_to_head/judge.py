"""Cross-vendor judge — protocol §3 table.

Pairing (load-bearing for §11.3 blind judging):
  - Haiku 4.5 generator answers      → judged by GPT-4o
  - Gemini 2.0 Flash generator answers → judged by Claude Opus 4.7
  - GPT-4o-mini generator answers    → judged by Claude Opus 4.7

Single-judge fallback (budget-tight): all answers judged by Opus only;
flag Haiku-judged-by-Opus as same-vendor in the manifest.

precondition: candidate answers are shuffled per-question with seed
  ``JUDGE_SHUFFLE_BASE + question_id_hash`` (protocol §4); judge sees only
  ``(question, gold, ability_tag, candidate)`` — never condition labels,
  never generator identities, never retrieved context.
postcondition: returns a list of ``JudgeVerdict`` records, one per
  candidate, in the original (un-shuffled) condition order. The shuffle
  is reversed inside this module so callers don't need to track it.
invariant: judge.py never receives the condition label or the generator
  ID at the prompt level — only at metadata-tracking level so we can
  reverse the shuffle.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from typing import Literal

from benchmarks.llm_head_to_head.generator import GeneratorResponse, call_generator


# Protocol §3 cross-vendor pairing table.
JUDGE_FOR_GENERATOR: dict[str, str] = {
    "claude-haiku-4-5-20251001": "gpt-4o-2024-11-20",
    "gemini-2.0-flash": "claude-opus-4-7-20260301",
    "gpt-4o-mini-2024-07-18": "claude-opus-4-7-20260301",
}

# Single-judge fallback (protocol §3 budget-tight mode).
SINGLE_JUDGE_MODEL = "claude-opus-4-7-20260301"


VerdictLabel = Literal[
    "correct", "partial", "incorrect", "abstain_correct", "abstain_wrong"
]


@dataclass(frozen=True)
class JudgeVerdict:
    condition: str  # 'A' | 'B' | 'C' | 'D'
    verdict: VerdictLabel
    raw_judge_id: int  # the shuffled id (1-4) the judge saw — for audit


@dataclass(frozen=True)
class JudgePanel:
    verdicts: list[JudgeVerdict]
    judge_model: str
    judge_response: GeneratorResponse


def _shuffle_seed_for(question_id: str) -> int:
    """Stable seed per question for the answer-shuffle.

    pre: ``question_id`` is the BeamItem identifier (deterministic across runs).
    post: returns a non-negative int derived from a stable hash of the id.
    """
    # Deterministic hash via Python's ``hash`` is process-salted; use
    # a stable arithmetic on the bytes instead.
    h = 0
    for ch in question_id:
        h = (h * 131 + ord(ch)) & 0x7FFFFFFF
    # Add the protocol-fixed shuffle-seed base so different runs of the
    # same code produce the SAME shuffles (protocol §10 manifest field
    # ``shuffle_seed_base: 20260501``).
    from benchmarks.llm_head_to_head.data_loader import JUDGE_SHUFFLE_BASE

    return JUDGE_SHUFFLE_BASE + h


def shuffle_candidates(
    question_id: str,
    candidates_by_condition: dict[str, str],
) -> tuple[list[tuple[int, str, str]], list[str]]:
    """Shuffle the four candidates and return (shuffled, condition_order_for_reverse).

    pre:
      - ``candidates_by_condition`` has exactly the condition keys present
        in the run (subset of {'A','B','C','D'}).
      - ``question_id`` is the BeamItem.question_id.
    post:
      - first return: list of ``(shuffled_id, condition, candidate_text)``
        in shuffled (judge-visible) order. shuffled_id ∈ 1..N.
      - second return: list of conditions in original alphabetic order
        (the order callers want their results reported in). Used to
        reverse the shuffle.
    """
    rng = random.Random(_shuffle_seed_for(question_id))
    original_order = sorted(candidates_by_condition.keys())
    shuffled = list(original_order)
    rng.shuffle(shuffled)
    out: list[tuple[int, str, str]] = []
    for shuffled_id, cond in enumerate(shuffled, start=1):
        out.append((shuffled_id, cond, candidates_by_condition[cond]))
    return out, original_order


def render_judge_prompt(
    question: str,
    ability: str,
    gold: str,
    support: str,
    shuffled: list[tuple[int, str, str]],
    template: str,
) -> str:
    """Render Appendix B with up to 4 candidates filled in.

    pre: ``template`` is the contents of ``prompts/judge.md``.
    post: every ``{CAND_i}`` placeholder is filled with the shuffled
      candidate text or ``[no candidate]`` if missing (when a condition
      is excluded from the run).
    """
    by_id = {sid: text for sid, _, text in shuffled}
    filled = (
        template
        .replace("{QUESTION}", question)
        .replace("{ABILITY}", ability)
        .replace("{GOLD}", gold or "[NO ANSWER]")
        .replace("{SUPPORT}", support or "(none)")
        .replace("{CAND_1}", by_id.get(1, "[no candidate]"))
        .replace("{CAND_2}", by_id.get(2, "[no candidate]"))
        .replace("{CAND_3}", by_id.get(3, "[no candidate]"))
        .replace("{CAND_4}", by_id.get(4, "[no candidate]"))
    )
    return filled


def parse_judge_output(
    text: str, shuffled: list[tuple[int, str, str]]
) -> list[JudgeVerdict]:
    """Parse the judge's JSONL output into per-condition verdicts.

    pre: ``text`` is the raw judge response. Per Appendix B, it is one
      JSON object per line with keys ``id`` and ``verdict``.
    post: returns a list of ``JudgeVerdict`` ordered by alphabetic
      condition (A, B, C, D — whichever subset is present). Missing or
      unparseable lines yield ``verdict='incorrect'`` as a conservative
      default (a missing verdict cannot count as correct).
    """
    id_to_cond = {sid: cond for sid, cond, _ in shuffled}
    parsed: dict[int, VerdictLabel] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        sid = obj.get("id")
        verdict = obj.get("verdict")
        if isinstance(sid, int) and verdict in (
            "correct",
            "partial",
            "incorrect",
            "abstain_correct",
            "abstain_wrong",
        ):
            parsed[sid] = verdict  # type: ignore[assignment]

    out: list[JudgeVerdict] = []
    for sid, cond, _ in sorted(shuffled, key=lambda t: t[1]):
        verdict_label: VerdictLabel = parsed.get(sid, "incorrect")
        out.append(
            JudgeVerdict(condition=cond, verdict=verdict_label, raw_judge_id=sid)
        )
    return out


def judge_item(
    question_id: str,
    question: str,
    ability: str,
    gold: str,
    support: str,
    candidates_by_condition: dict[str, str],
    judge_template: str,
    generator_model_id: str,
    judge_mode: str = "cross_vendor",
    dry_run: bool = False,
) -> JudgePanel:
    """Run one judge call for one BEAM item.

    pre:
      - ``candidates_by_condition`` keys ⊆ {'A','B','C','D'}.
      - ``judge_mode`` ∈ {'cross_vendor', 'single_judge_opus'}.
      - ``generator_model_id`` is needed to look up the cross-vendor judge.
    post:
      - returns ``JudgePanel`` with per-condition verdicts in alphabetic
        condition order.
      - on dry_run: judge call is stubbed; verdicts default to 'incorrect'.
    """
    shuffled, _ = shuffle_candidates(question_id, candidates_by_condition)
    prompt = render_judge_prompt(question, ability, gold, support, shuffled, judge_template)

    if judge_mode == "single_judge_opus":
        judge_model = SINGLE_JUDGE_MODEL
    else:
        if generator_model_id not in JUDGE_FOR_GENERATOR:
            raise ValueError(
                f"No cross-vendor judge configured for {generator_model_id!r}. "
                "Add an entry to JUDGE_FOR_GENERATOR or use single_judge_opus."
            )
        judge_model = JUDGE_FOR_GENERATOR[generator_model_id]

    response = call_generator(
        model_id=judge_model,
        prompt=prompt,
        max_output_tokens=512,
        temperature=0.0,
        dry_run=dry_run,
    )
    verdicts = parse_judge_output(response.text, shuffled)
    return JudgePanel(verdicts=verdicts, judge_model=judge_model, judge_response=response)
