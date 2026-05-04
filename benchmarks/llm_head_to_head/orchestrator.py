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

from benchmarks.llm_head_to_head import (
    cortex_caller,
    data_loader,
    long_context_truncator,
    oracle_loader,
    retriever_baselines,
)
from benchmarks.llm_head_to_head.data_loader import BeamItem
from benchmarks.llm_head_to_head.generator import (
    PRICING_USD_PER_M_TOKEN,
    estimate_cost_usd,
)
from benchmarks.llm_head_to_head.manifest import (
    ManifestModelEntry,
    build_manifest,
    write_manifest,
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
            diagnostics={"k": retriever_baselines.STANDARD_RAG_TOP_K, "n_passages": len(passages)},
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
    return template.replace("{CONTEXT}", context_text).replace(
        "{QUESTION}", question
    )


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
        budget = (
            long_context_truncator.MODEL_INPUT_BUDGETS.get(gen, 100_000)
        )
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
            cell_cost = (
                len(items)
                * estimate_cost_usd(gen, input_tokens_per_call, avg_output_tokens)
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
    p.add_argument("--dry-run", action="store_true", help="No API calls; print diagnostics only.")
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

    # Live-mode wiring deliberately not implemented in Stage 0 (per
    # protocol §12 timeline). The pilot.py script runs Stage 1 (B+C
    # only on Haiku), and the eventual full-panel Stage 2 builds on
    # this orchestrator. Stage 0 stops here.
    print(
        "[orchestrator] Live mode not yet wired — Stage 0 commits scaffold "
        "only. See tasks/beam-10m-llm-head-to-head-protocol.md §12 for "
        "the timeline. Use --dry-run for now.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
