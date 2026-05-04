"""Pilot (Stage 1) — Haiku 4.5 × {B, C} × 196 items + GPT-4o judge.

Per protocol §8: cheapest stress-test of the harness. Conditions A and D
are skipped in pilot because they're not load-bearing for the §8 GO/NO-GO
gate (which checks judge κ, end-to-end success rate, and B-vs-C signal
direction).

This file's --dry-run mode is the Stage-0 deliverable. It:
  1. Loads N BEAM items (default 3).
  2. Builds condition contexts for A, B, C, D — verifying every builder
     produces a non-degenerate output without firing any API.
  3. Prints token counts, retrieved-passage counts, oracle-turn counts.
  4. Renders the answer prompt that WOULD be sent to the generator.
  5. Estimates Stage 2.1 cost.
  6. Does NOT call any vendor API; does NOT touch the production DB
     (condition C is stubbed in dry-run mode — see below).

precondition: ``--dry-run`` is sufficient for Stage 0. Live pilot
  requires API keys + production DB seeded with BEAM memories per
  protocol §12 timeline.
postcondition: --dry-run exits 0 with diagnostic prints; live pilot
  exits non-zero in this PR (Stage 0 deliberately does not wire live).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from benchmarks.llm_head_to_head import (
    data_loader,
    long_context_truncator,
    oracle_loader,
)
from benchmarks.llm_head_to_head.data_loader import BeamItem
from benchmarks.llm_head_to_head.generator import estimate_cost_usd
from benchmarks.llm_head_to_head.orchestrator import (
    PROMPTS_DIR,
    estimate_run_cost,
    render_answer_prompt,
)


# Stage 1 cell selection (protocol §8): Haiku × {B, C} × 196 items.
PILOT_GENERATOR = "claude-haiku-4-5-20251001"
PILOT_JUDGE = "gpt-4o-2024-11-20"
PILOT_CONDITIONS = ("B", "C")

# Stage 2.1 cell selection for cost estimate output.
STAGE2_1_CONDITIONS = ("A", "B", "C", "D")


def _pretty_token_count(n: int) -> str:
    if n < 1_000:
        return f"{n} tok"
    return f"{n / 1_000:.1f}k tok"


def _build_dryrun_context(condition: str, item: BeamItem) -> tuple[str, dict[str, Any]]:
    """Build a condition's context WITHOUT touching the DB or production stack.

    Conditions A and D are pure offline: A truncates the BEAM turn list,
    D looks up oracle turns. They run in dry-run as-is.

    Conditions B and C require runtime resources we don't want to spin
    up at scaffold time:
      - B needs a per-conversation BenchmarkDB with memories loaded into
        an HNSW-indexed table.
      - C needs the production memory store seeded under domain="beam".
    For dry-run we emit a placeholder block with the budget envelope
    (~4500 tokens per protocol §7) so the prompt rendering is exercised
    end-to-end. The token counts in the cost estimate use the same §7
    figures.

    pre: ``condition`` ∈ {'A','B','C','D'}.
    post: returns (text, diagnostics).
    """
    if condition == "A":
        budget = long_context_truncator.input_budget_for(PILOT_GENERATOR)
        res = long_context_truncator.build_naive_long_context(item, budget)
        return res.text, {
            "condition": "A",
            "input_tokens": res.input_tokens,
            "truncated": res.truncated,
            "budget": budget,
        }
    if condition == "B":
        placeholder = (
            "[DRY RUN PLACEHOLDER — Condition B would be top-20 cosine RAG "
            "passages here. Live mode requires a per-conversation BenchmarkDB "
            "with the BEAM memories indexed under HNSW cosine.]"
        )
        return placeholder, {
            "condition": "B",
            "input_tokens": 4_500,
            "n_passages_planned": 20,
        }
    if condition == "C":
        placeholder = (
            "[DRY RUN PLACEHOLDER — Condition C would call "
            "mcp_server.handlers.recall.handler with the seeded BEAM memories. "
            "Live mode requires the production memory store seeded under "
            "domain='beam' before the pilot runs.]"
        )
        return placeholder, {
            "condition": "C",
            "input_tokens": 4_500,
            "n_memories_planned": 20,
        }
    if condition == "D":
        passages = oracle_loader.build_oracle_context(item)
        text = oracle_loader.passages_to_context(passages)
        return text, {
            "condition": "D",
            "input_tokens": long_context_truncator._heuristic_token_count(text),
            "n_supporting_turns": len(passages),
            "n_requested": len(item.source_chat_ids),
        }
    raise ValueError(f"Unknown condition: {condition!r}")


def dry_run(n: int, split: str = "10M") -> int:
    """Build the four conditions for N items and print diagnostics."""
    print(f"=== BEAM-10M H2H pilot dry-run: {n} item(s), split={split} ===\n")

    try:
        items_iter = data_loader.iter_items(split)
    except Exception as e:
        print(
            f"[pilot] could not load BEAM-{split} dataset: {type(e).__name__}: {e}",
            file=sys.stderr,
        )
        print(
            "[pilot] In dry-run mode this is fatal — we need real items "
            "to demonstrate context builders. Install `datasets` and ensure "
            "network access, then retry. (Production runs cache the dataset "
            "after first pull.)",
            file=sys.stderr,
        )
        return 3

    answer_template = (PROMPTS_DIR / "answer.md").read_text()

    items_done = 0
    for item in items_iter:
        if items_done >= n:
            break
        items_done += 1
        print(f"--- item {items_done}/{n}: {item.question_id} ---")
        print(f"  ability     : {item.ability}")
        print(f"  question    : {item.question[:100]!r}")
        print(f"  gold        : {(item.gold_answer or '[NO ANSWER]')[:100]!r}")
        print(f"  source_ids  : {len(item.source_chat_ids)} turns")
        print(f"  conv turns  : {len(item.turns)} (full conversation)")

        for cond in ("A", "B", "C", "D"):
            text, diag = _build_dryrun_context(cond, item)
            print(f"  [{cond}] {diag}")
            # Print first 200 chars of rendered prompt so the reader can
            # eyeball the format without 196k tokens of dump.
            rendered = render_answer_prompt(answer_template, text, item.question)
            preview = rendered[:240].replace("\n", " ⏎ ")
            print(f"  [{cond}] prompt preview: {preview!r}")
        print()

    if items_done == 0:
        print("[pilot] no items found — dataset returned empty.", file=sys.stderr)
        return 4

    # Cost estimates.
    print("=== Cost estimates ===\n")

    # Stage 1 pilot: Haiku × {B, C} × 196 items + 1 judge.
    pilot_cost = estimate_run_cost(
        items=[None] * data_loader.EXPECTED_ITEM_COUNT,  # type: ignore[list-item]
        conditions=PILOT_CONDITIONS,
        generator_models=(PILOT_GENERATOR,),
        judge_models=(PILOT_JUDGE,),
    )
    print(
        f"Stage 1 pilot ({PILOT_GENERATOR} × {{B,C}} × 196 items, judge {PILOT_JUDGE}):"
    )
    print(f"  generators  : ${pilot_cost['generator_subtotal_usd']:.2f}")
    print(f"  judge       : ${pilot_cost['judge_subtotal_usd']:.2f}")
    print(f"  TOTAL       : ${pilot_cost['total_usd']:.2f}")
    print()

    # Stage 2.1 slim: Haiku × {A,B,C,D} × 196 items + GPT-4o judge.
    s21_cost = estimate_run_cost(
        items=[None] * data_loader.EXPECTED_ITEM_COUNT,  # type: ignore[list-item]
        conditions=STAGE2_1_CONDITIONS,
        generator_models=(PILOT_GENERATOR,),
        judge_models=(PILOT_JUDGE,),
    )
    print(
        f"Stage 2.1 ({PILOT_GENERATOR} × {{A,B,C,D}} × 196 items, judge {PILOT_JUDGE}):"
    )
    for cell in s21_cost["cells"]:
        print(
            f"  cell {cell['generator']} × {cell['condition']}: "
            f"${cell['subtotal_usd']:.2f} "
            f"({cell['input_tokens_per_call']:,} input toks/call)"
        )
    print(f"  generators  : ${s21_cost['generator_subtotal_usd']:.2f}")
    print(f"  judge       : ${s21_cost['judge_subtotal_usd']:.2f}")
    print(f"  TOTAL       : ${s21_cost['total_usd']:.2f}")
    print()

    print(
        "(Per protocol §7: 30% retry/variance buffer brings Stage 2.1 to "
        "$40-60 95% CI; user budget cap = $80.)"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="BEAM-10M H2H pilot (Stage 1)")
    p.add_argument("--dry-run", action="store_true", help="No API calls.")
    p.add_argument("--n", type=int, default=3, help="Items in dry-run.")
    p.add_argument("--split", default="10M", help="BEAM split (10M is the protocol universe).")
    args = p.parse_args(argv)

    if not args.dry_run:
        print(
            "[pilot] Live pilot is not wired in Stage 0. Use --dry-run.",
            file=sys.stderr,
        )
        return 2

    return dry_run(args.n, args.split)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    sys.exit(main())
