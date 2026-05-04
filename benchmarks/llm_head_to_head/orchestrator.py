"""Orchestrator — wires conditions × generators × judges over 196 items.

This is the composition root for the harness (per coding-standards §2.3).
It is the ONLY layer that imports from all four condition builders, the
generator, the judge, and the manifest. Each piece below has a single
responsibility; this module is the only place they're stitched together.

precondition:
  - The orchestrator is invoked from the project repo root so relative
    paths to ``benchmarks/llm_head_to_head/prompts/`` resolve.
  - For non-dry-run modes: ``ANTHROPIC_API_KEY`` and/or ``GOOGLE_API_KEY``
    are set (depending on which generators / judges are selected).
  - For condition C: the BEAM conversation memories have been seeded into
    the production memory store under ``domain="beam"`` BEFORE the
    orchestrator runs (the protocol's seeding step is a separate pre-run
    operation; not run here to keep the contract narrow).
postcondition:
  - In dry-run mode: builds all 4 condition contexts for the requested
    items and prints diagnostic information (token counts, cost estimate).
    NO API calls. NO writes to the manifest beyond the directory scaffold.
  - In live mode (NOT exercised in this Stage 0 PR): for each item, calls
    each generator under each condition with the answer prompt, judges
    via cross-vendor judge, appends the result to ``items.jsonl``, and
    updates the manifest's ``cost_tracking`` totals.
invariant:
  - Same-question-id ⇒ same shuffle seed (protocol §11.5 anti-cheating).
  - Conditions for one item all use the SAME ``BeamItem`` instance, so
    they see identical conversation context. The IV-1 manipulation is
    purely the context-builder choice.
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from benchmarks.llm_head_to_head import (
    cortex_caller,
    long_context_truncator,
    oracle_loader,
    retriever_baselines,
)
from benchmarks.llm_head_to_head.data_loader import BeamItem
from benchmarks.llm_head_to_head.generator import (
    GeneratorError,
    GeneratorResponse,
    call_generator,
    estimate_cost_usd,
)
from benchmarks.llm_head_to_head.judge import (
    JudgePanel,
    judge_item,
)
from benchmarks.llm_head_to_head.manifest import (
    ItemResultLine,
    append_item_result,
    update_cost_tracking,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
PROMPTS_DIR = Path(__file__).parent / "prompts"
RESULTS_DIR = Path(__file__).parent / "results"


# Pre-registered conditions — protocol §2.
ALL_CONDITIONS = ("A", "B", "C", "D")


@dataclass(frozen=True)
class ConditionContext:
    """The context block fed to the answer-prompt under one condition."""

    condition: str  # 'A' | 'B' | 'C' | 'D'
    text: str
    estimated_input_tokens: int
    diagnostics: dict


def build_context(
    condition: str,
    item: BeamItem,
    generator_model_id: str,
    db_for_rag,  # BenchmarkDB-like; only used by condition B
) -> ConditionContext:
    """Dispatch to the right condition builder.

    pre: ``condition`` ∈ ALL_CONDITIONS.
    post: returns a ConditionContext with text and a diagnostics dict
      (per-condition info: e.g. number of passages retrieved, truncation
      flag for A).
    """
    if condition == "A":
        budget = long_context_truncator.input_budget_for(generator_model_id)
        result = long_context_truncator.build_naive_long_context(
            item, input_token_budget=budget
        )
        return ConditionContext(
            condition="A",
            text=result.text,
            estimated_input_tokens=result.input_tokens,
            diagnostics={"truncated": result.truncated, "budget": budget},
        )
    if condition == "B":
        if db_for_rag is None:
            raise ValueError(
                "Condition B (standard RAG) requires a BenchmarkDB instance "
                "for the per-conversation ephemeral PG store."
            )
        passages = retriever_baselines.standard_rag(item.question, db_for_rag)
        text = retriever_baselines.passages_to_context(passages)
        return ConditionContext(
            condition="B",
            text=text,
            estimated_input_tokens=long_context_truncator._heuristic_token_count(text),
            diagnostics={
                "k": retriever_baselines.STANDARD_RAG_TOP_K,
                "n_passages": len(passages),
            },
        )
    if condition == "C":
        memories = cortex_caller.cortex_recall(item.question, domain="beam")
        text = cortex_caller.passages_to_context(memories)
        return ConditionContext(
            condition="C",
            text=text,
            estimated_input_tokens=long_context_truncator._heuristic_token_count(text),
            diagnostics={
                "max_results": cortex_caller.CORTEX_MAX_RESULTS,
                "n_memories": len(memories),
            },
        )
    if condition == "D":
        passages = oracle_loader.build_oracle_context(item)
        text = oracle_loader.passages_to_context(passages)
        return ConditionContext(
            condition="D",
            text=text,
            estimated_input_tokens=long_context_truncator._heuristic_token_count(text),
            diagnostics={
                "n_supporting_turns": len(passages),
                "n_requested": len(item.source_chat_ids),
            },
        )
    raise ValueError(f"Unknown condition: {condition!r}")


def render_answer_prompt(template: str, context_text: str, question: str) -> str:
    """Fill Appendix A with the context and question.

    pre: ``template`` is the contents of ``prompts/answer.md``.
    post: returns the fully rendered prompt string.
    """
    return template.replace("{CONTEXT}", context_text).replace("{QUESTION}", question)


def estimate_run_cost(
    items: list[BeamItem],
    conditions: tuple[str, ...],
    generator_models: tuple[str, ...],
    judge_models: tuple[str, ...],
) -> dict:
    """Estimate the USD cost of a full run before firing.

    pre: all generator/judge model ids are in PRICING_USD_PER_M_TOKEN.
    post: returns a dict with per-cell and totals; output token estimate
      uses 150 tokens/answer (protocol §7 estimate; will measure 99th
      percentile in pilot).
    """
    avg_output_tokens = 150
    total = 0.0
    cells: list[dict] = []
    for gen in generator_models:
        budget = long_context_truncator.MODEL_INPUT_BUDGETS.get(gen, 100_000)
        for cond in conditions:
            if cond == "A":
                # naive long-context: full window-sized input
                input_tokens_per_call = budget
            elif cond in ("B", "C"):
                input_tokens_per_call = 4_500  # protocol §7 estimate
            elif cond == "D":
                input_tokens_per_call = 1_500  # protocol §7 estimate
            else:
                input_tokens_per_call = 0
            cell_cost = len(items) * estimate_cost_usd(
                gen, input_tokens_per_call, avg_output_tokens
            )
            total += cell_cost
            cells.append(
                {
                    "generator": gen,
                    "condition": cond,
                    "items": len(items),
                    "input_tokens_per_call": input_tokens_per_call,
                    "subtotal_usd": round(cell_cost, 2),
                }
            )

    judge_input_per_call = 5_500
    judge_output_per_call = 100
    judge_total = 0.0
    judge_calls = len(items) * len(generator_models)
    for jm in judge_models:
        per_call = estimate_cost_usd(jm, judge_input_per_call, judge_output_per_call)
        # In cross-vendor mode, each judge is responsible for some subset
        # of generators — the caller passes the right list. Approximate
        # by even split across passed judges.
        judge_total += per_call * judge_calls / max(1, len(judge_models))

    return {
        "generator_subtotal_usd": round(total, 2),
        "judge_subtotal_usd": round(judge_total, 2),
        "total_usd": round(total + judge_total, 2),
        "cells": cells,
    }


# ── CLI ──────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="BEAM-10M LLM Head-to-Head Orchestrator (Stage 0 scaffold)"
    )
    p.add_argument(
        "--dry-run", action="store_true", help="No API calls; print diagnostics only."
    )
    p.add_argument("--n", type=int, default=3, help="Item count (dry-run only).")
    p.add_argument(
        "--generators",
        default="claude-haiku-4-5-20251001",
        help="Comma-separated generator pins.",
    )
    p.add_argument(
        "--judges",
        default="gpt-4o-2024-11-20",
        help="Comma-separated judge pins.",
    )
    p.add_argument(
        "--conditions",
        default="A,B,C,D",
        help="Comma-separated subset of A,B,C,D.",
    )
    p.add_argument("--run-id", default=time.strftime("dryrun-%Y%m%dT%H%M%SZ"))
    args = p.parse_args(argv)

    generators = tuple(args.generators.split(","))
    judges = tuple(args.judges.split(","))
    conditions = tuple(args.conditions.split(","))

    cost = estimate_run_cost(
        items=[None] * args.n,  # type: ignore[list-item]  # only len() matters here
        conditions=conditions,
        generator_models=generators,
        judge_models=judges,
    )

    print(f"[orchestrator] run_id={args.run_id}")
    print(f"[orchestrator] generators={generators}")
    print(f"[orchestrator] judges={judges}")
    print(f"[orchestrator] conditions={conditions}")
    print(f"[orchestrator] expected cost USD ≈ {cost['total_usd']}")
    if args.dry_run:
        print("[orchestrator] DRY RUN — no API calls made.")
        return 0

    # Live-mode CLI is intentionally minimal — pilot.py is the canonical
    # entry point for Stage 1 (B+C on Haiku) and forwards into ``run_live``
    # below. The orchestrator's CLI here exists only for ad-hoc smoke runs.
    print(
        "[orchestrator] Live mode CLI not implemented; use "
        "`python -m benchmarks.llm_head_to_head.pilot --run` to fire a "
        "live pilot. The orchestrator library functions (run_live, "
        "build_context) are imported by pilot.py.",
        file=sys.stderr,
    )
    return 2


# ── Live runner ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class LiveCellResult:
    """One (item × condition × generator) cell after live execution."""

    question_id: str
    ability: str
    condition: str
    generator_model: str
    generator_response: str
    input_tokens: int
    output_tokens: int
    retry_count: int
    estimated_usd: float
    wall_time_s: float


def _generate_one_cell(
    item: BeamItem,
    condition: str,
    generator_model: str,
    answer_template: str,
    db_for_rag: Any,
) -> LiveCellResult:
    """Build the condition's context, render the prompt, fire one generator call.

    pre:
      - ``condition`` ∈ ALL_CONDITIONS.
      - ``answer_template`` is the contents of ``prompts/answer.md``.
      - For B: ``db_for_rag`` is a BenchmarkDB-like with the BEAM memories
        already loaded under ``domain='beam'``.
      - For C: the production memory store has been seeded with the same
        memories under ``domain='beam'``.
    post:
      - returns one ``LiveCellResult``; raises ``GeneratorError`` if the
        vendor call exhausted retries (so the caller can decide whether
        to skip the cell or abort the run).
    """
    ctx = build_context(condition, item, generator_model, db_for_rag)
    prompt = render_answer_prompt(answer_template, ctx.text, item.question)

    t0 = time.time()
    response: GeneratorResponse = call_generator(
        model_id=generator_model,
        prompt=prompt,
        max_output_tokens=4_000,
        temperature=0.0,
        dry_run=False,
    )
    wall = time.time() - t0

    cost = estimate_cost_usd(
        generator_model, response.input_tokens, response.output_tokens
    )
    return LiveCellResult(
        question_id=item.question_id,
        ability=item.ability,
        condition=condition,
        generator_model=generator_model,
        generator_response=response.text,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        retry_count=len(response.retries),
        estimated_usd=cost,
        wall_time_s=wall,
    )


def _format_support_for_judge(item: BeamItem) -> str:
    """Render the gold supporting turns for the judge prompt's SUPPORT field.

    pre: ``item`` carries source_chat_ids that index into ``item.turns``.
    post: returns a concatenation of supporting turn texts; empty string
      when ``source_chat_ids`` is empty (abstention items).
    """
    passages = oracle_loader.build_oracle_context(item)
    return oracle_loader.passages_to_context(passages)


def run_live(
    items: list[BeamItem],
    conditions: tuple[str, ...],
    generator_model: str,
    judge_mode: str,
    results_dir: Path,
    answer_template: str,
    judge_template: str,
    db_for_rag: Any,
    cost_ceiling_usd: float,
) -> dict[str, Any]:
    """End-to-end live run. Builds contexts, generates answers, judges, writes manifest.

    pre:
      - ``items`` is non-empty.
      - ``conditions`` ⊆ ALL_CONDITIONS.
      - ``generator_model`` is in ``VENDOR_BY_MODEL`` and has a configured judge.
      - ``results_dir`` already contains a manifest.json (caller wrote it
        before calling this function); we only append items.jsonl + patch
        cost_tracking.
      - ``cost_ceiling_usd`` is a hard limit; we abort and return early
        with ``{'aborted': True, ...}`` if the running total exceeds it
        (defence-in-depth on Stage 0 budget cap).
    post:
      - returns a summary dict with totals, per-cell results, and judge
        verdicts.
      - one items.jsonl line per (item × condition) is appended.
      - manifest.json's cost_tracking is incremented.
    """
    manifest_path = results_dir / "manifest.json"
    summary: dict[str, Any] = {
        "items": len(items),
        "conditions": list(conditions),
        "generator": generator_model,
        "judge_mode": judge_mode,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
        "total_usd": 0.0,
        "cells_run": 0,
        "cells_failed": 0,
        "judge_calls": 0,
        "aborted": False,
    }

    # Track running total to enforce ``cost_ceiling_usd``. The estimate
    # is conservative (sum of generator + judge cells already completed).
    total_usd = 0.0
    total_input = 0
    total_output = 0

    for item_idx, item in enumerate(items, start=1):
        if total_usd > cost_ceiling_usd:
            summary["aborted"] = True
            summary["abort_reason"] = (
                f"cost_ceiling exceeded after {item_idx - 1} items "
                f"(total ${total_usd:.4f} > ceiling ${cost_ceiling_usd:.4f})"
            )
            print(f"[orchestrator] {summary['abort_reason']}", file=sys.stderr)
            break

        print(
            f"[orchestrator] item {item_idx}/{len(items)} "
            f"({item.question_id}, ability={item.ability})",
            file=sys.stderr,
        )

        candidates_by_condition: dict[str, str] = {}
        cell_results: list[LiveCellResult] = []
        for cond in conditions:
            try:
                cell = _generate_one_cell(
                    item=item,
                    condition=cond,
                    generator_model=generator_model,
                    answer_template=answer_template,
                    db_for_rag=db_for_rag,
                )
            except GeneratorError as e:
                print(
                    f"[orchestrator] cell {item.question_id}/{cond} failed: {e}",
                    file=sys.stderr,
                )
                summary["cells_failed"] += 1
                continue

            cell_results.append(cell)
            candidates_by_condition[cond] = cell.generator_response
            total_usd += cell.estimated_usd
            total_input += cell.input_tokens
            total_output += cell.output_tokens
            summary["cells_run"] += 1

        if not candidates_by_condition:
            print(
                f"[orchestrator] all cells for {item.question_id} failed; "
                "skipping judge",
                file=sys.stderr,
            )
            continue

        # Judge: one call, judges all conditions for this item via the
        # cross-vendor pairing in JUDGE_FOR_GENERATOR (or single-judge Opus).
        try:
            panel: JudgePanel = judge_item(
                question_id=item.question_id,
                question=item.question,
                ability=item.ability,
                gold=item.gold_answer or "",
                support=_format_support_for_judge(item),
                candidates_by_condition=candidates_by_condition,
                judge_template=judge_template,
                generator_model_id=generator_model,
                judge_mode=judge_mode,
                dry_run=False,
            )
        except GeneratorError as e:
            print(
                f"[orchestrator] judge failed for {item.question_id}: {e}",
                file=sys.stderr,
            )
            # Cells still produced answers — record with judge_label="error"
            # rather than dropping them silently.
            for cell in cell_results:
                _emit_item_line(
                    results_dir,
                    cell,
                    judge_label="error",
                )
            continue

        verdict_by_cond = {v.condition: v.verdict for v in panel.verdicts}
        judge_cost = estimate_cost_usd(
            panel.judge_model,
            panel.judge_response.input_tokens,
            panel.judge_response.output_tokens,
        )
        total_usd += judge_cost
        total_input += panel.judge_response.input_tokens
        total_output += panel.judge_response.output_tokens
        summary["judge_calls"] += 1

        for cell in cell_results:
            label = verdict_by_cond.get(cell.condition, "incorrect")
            _emit_item_line(results_dir, cell, judge_label=label)

    summary["total_input_tokens"] = total_input
    summary["total_output_tokens"] = total_output
    summary["total_usd"] = round(total_usd, 6)

    # Patch manifest cost_tracking.
    if manifest_path.exists():
        update_cost_tracking(
            manifest_path,
            add_input_tokens=total_input,
            add_output_tokens=total_output,
            add_usd=total_usd,
        )
    return summary


def _emit_item_line(results_dir: Path, cell: LiveCellResult, judge_label: str) -> None:
    """Write one items.jsonl row for a completed (or judge-failed) cell.

    pre: ``judge_label`` is one of the protocol verdicts OR the literal
      ``'error'`` (judge call failed; the cell answer is preserved for audit).
    post: appends one JSONL line; never raises (failures here would mask
      cost-tracking already incremented).
    """
    append_item_result(
        results_dir,
        ItemResultLine(
            question_id=cell.question_id,
            ability=cell.ability,
            condition=cell.condition,
            generator_model=cell.generator_model,
            generator_response=cell.generator_response,
            judge_label=judge_label,
            input_tokens=cell.input_tokens,
            output_tokens=cell.output_tokens,
            retry_count=cell.retry_count,
            estimated_usd=cell.estimated_usd,
            wall_time_s=cell.wall_time_s,
        ),
    )


if __name__ == "__main__":
    sys.exit(main())
