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
import time
from pathlib import Path
from typing import Any

from benchmarks.llm_head_to_head import (
    data_loader,
    long_context_truncator,
    oracle_loader,
)
from benchmarks.llm_head_to_head.data_loader import BeamItem
from benchmarks.llm_head_to_head.generator import estimate_cost_usd
from benchmarks.llm_head_to_head.manifest import (
    ManifestModelEntry,
    build_manifest,
    write_manifest,
)
from benchmarks.llm_head_to_head.orchestrator import (
    PROMPTS_DIR,
    RESULTS_DIR,
    estimate_run_cost,
    render_answer_prompt,
    run_live,
)


# Stage 1 cell selection (protocol §8): Haiku × {B, C} × 196 items.
PILOT_GENERATOR = "claude-haiku-4-5-20251001"
PILOT_JUDGE = "gpt-4o-2024-11-20"
PILOT_CONDITIONS = ("B", "C")

# Map CLI shorthand → fully pinned model id (protocol §3 vendor pins).
GENERATOR_ALIASES: dict[str, str] = {
    "haiku": "claude-haiku-4-5-20251001",
    "opus": "claude-opus-4-7-20260301",
    "gpt-4o-mini": "gpt-4o-mini-2024-07-18",
    "gemini-2.0-flash": "gemini-2.0-flash",
}

JUDGE_ALIASES: dict[str, str] = {
    "gpt4o": "gpt-4o-2024-11-20",
    "gpt-4o": "gpt-4o-2024-11-20",
    "opus": "claude-opus-4-7-20260301",
}

# Stage 0 hard ceiling (task constraint: total smoke spend ≤ $0.15).
SMOKE_COST_CEILING_USD = 0.15

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


def run_pilot_live(
    n: int,
    generator_alias: str,
    judge_alias: str,
    output_dir: Path,
    split: str = "10M",
    cost_ceiling_usd: float = SMOKE_COST_CEILING_USD,
) -> int:
    """Stage-0 / Stage-1 LIVE pilot — real API calls, real judge, real manifest.

    pre:
      - ``ANTHROPIC_API_KEY`` and ``OPENAI_API_KEY`` are set in the env
        (the cross-vendor judge needs both for the Haiku × GPT-4o pairing).
      - ``DATABASE_URL`` points at the local Cortex Postgres; pgvector +
        pg_trgm extensions installed; production schema migrated.
      - Network reachable for Anthropic + OpenAI APIs.
    post:
      - Writes ``output_dir/manifest.json`` and ``output_dir/items.jsonl``.
      - Each item × condition cell appears as one items.jsonl line with
        a real generator_response and judge_label.
      - Returns 0 on success (all cells produced); 4 on cost-ceiling abort;
        5 on dataset load failure; 6 on DB connection failure.
    invariant:
      - The smoke is bounded by ``cost_ceiling_usd`` (defence-in-depth on
        the Stage 0 $0.15 cap); the run aborts mid-loop if exceeded.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    generator_model = GENERATOR_ALIASES.get(generator_alias, generator_alias)
    judge_model = JUDGE_ALIASES.get(judge_alias, judge_alias)

    # Pre-flight: load BEAM items.
    try:
        all_items_iter = data_loader.iter_items(split)
        items: list[BeamItem] = []
        for it in all_items_iter:
            if len(items) >= n:
                break
            items.append(it)
    except Exception as e:
        print(
            f"[pilot] failed to load BEAM-{split}: {type(e).__name__}: {e}",
            file=sys.stderr,
        )
        return 5
    if not items:
        print("[pilot] no items loaded; aborting.", file=sys.stderr)
        return 5

    # Pre-flight: open BenchmarkDB and seed memories under domain="beam".
    # This single DB instance serves BOTH:
    #   - Condition B (direct cosine query against the same memories table)
    #   - Condition C (production handler reads same memories table)
    # That's by design — protocol §2.B/C compares retrieval STACKS over
    # the same ground-truth memory population.
    try:
        from benchmarks.lib.bench_db import BenchmarkDB
    except Exception as e:
        print(
            f"[pilot] could not import BenchmarkDB: {type(e).__name__}: {e}",
            file=sys.stderr,
        )
        return 6

    print(
        f"[pilot] LIVE pilot: n={len(items)}, generator={generator_model}, "
        f"judge={judge_model}, ceiling=${cost_ceiling_usd}",
        file=sys.stderr,
    )
    print(f"[pilot] output_dir={output_dir}", file=sys.stderr)

    # Build the manifest scaffold up-front (write_manifest emits
    # manifest.json so cost_tracking can be patched later).
    repo_root = Path(__file__).resolve().parents[2]
    answer_prompt_path = PROMPTS_DIR / "answer.md"
    judge_prompt_path = PROMPTS_DIR / "judge.md"
    package_lockfile_path = repo_root / "uv.lock"
    pricing_snapshot_sha = "stage0-smoke-2026-05-02"

    manifest = build_manifest(
        run_id=output_dir.name,
        repo_root=repo_root,
        generator_models={
            "primary": ManifestModelEntry(
                api="anthropic" if generator_alias == "haiku" else "vendor",
                model_id=generator_model,
            )
        },
        judge_models={
            "primary": ManifestModelEntry(
                api="openai" if judge_alias.startswith("gpt") else "vendor",
                model_id=judge_model,
            )
        },
        judge_mode="cross_vendor",
        item_count=len(items),
        conditions=list(PILOT_CONDITIONS),
        pricing_snapshot_sha=pricing_snapshot_sha,
        answer_prompt_path=answer_prompt_path,
        judge_prompt_path=judge_prompt_path,
        package_lockfile_path=package_lockfile_path,
    )
    write_manifest(manifest, output_dir)

    answer_template = answer_prompt_path.read_text()
    judge_template = judge_prompt_path.read_text()

    # Open BenchmarkDB and seed BEAM memories. The seeded conversation
    # is whichever conv the items belong to; for n≤3 they share the same
    # conversation_idx in BEAM-10M (one mega-convo per record). We seed
    # ALL turns from the items' conversations, deduplicated by content.
    seen_convs: set[int] = set()
    rc = 0
    with BenchmarkDB() as db:
        all_memories: list[dict[str, Any]] = []
        seen_content: set[str] = set()
        for it in items:
            if it.conversation_idx in seen_convs:
                continue
            seen_convs.add(it.conversation_idx)
            for mem in it.memories:
                content = mem.get("content", "")
                if content and content not in seen_content:
                    seen_content.add(content)
                    all_memories.append(mem)
        print(
            f"[pilot] seeding {len(all_memories)} memories under domain='beam' "
            f"from {len(seen_convs)} conversations…",
            file=sys.stderr,
        )
        if all_memories:
            db.load_memories(all_memories, domain="beam")

        summary = run_live(
            items=items,
            conditions=PILOT_CONDITIONS,
            generator_model=generator_model,
            judge_mode="cross_vendor",
            results_dir=output_dir,
            answer_template=answer_template,
            judge_template=judge_template,
            db_for_rag=db,
            cost_ceiling_usd=cost_ceiling_usd,
        )

    print(f"[pilot] DONE. Summary: {summary}", file=sys.stderr)
    if summary.get("aborted"):
        rc = 4
    if summary.get("cells_failed", 0) > 0 and summary.get("cells_run", 0) == 0:
        rc = 7
    return rc


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="BEAM-10M H2H pilot (Stage 0/1)")
    p.add_argument("--dry-run", action="store_true", help="No API calls.")
    p.add_argument(
        "--run", action="store_true", help="LIVE pilot — fires real API calls."
    )
    p.add_argument("--n", type=int, default=3, help="Items in dry-run / smoke.")
    p.add_argument(
        "--generator",
        default="haiku",
        help="Generator alias (haiku|opus|gpt-4o-mini|gemini-2.0-flash).",
    )
    p.add_argument("--judge", default="gpt4o", help="Judge alias (gpt4o|opus).")
    p.add_argument("--output", default=None, help="Output directory for live run.")
    p.add_argument(
        "--cost-ceiling",
        type=float,
        default=SMOKE_COST_CEILING_USD,
        help="Hard USD cap; aborts mid-loop if exceeded.",
    )
    p.add_argument(
        "--split", default="10M", help="BEAM split (10M is the protocol universe)."
    )
    args = p.parse_args(argv)

    if args.dry_run and args.run:
        print("[pilot] --dry-run and --run are mutually exclusive.", file=sys.stderr)
        return 2

    if args.run:
        out = (
            Path(args.output)
            if args.output
            else RESULTS_DIR / f"smoke_{time.strftime('%Y%m%dT%H%M%SZ')}"
        )
        return run_pilot_live(
            n=args.n,
            generator_alias=args.generator,
            judge_alias=args.judge,
            output_dir=out,
            split=args.split,
            cost_ceiling_usd=args.cost_ceiling,
        )

    if args.dry_run:
        return dry_run(args.n, args.split)

    print(
        "[pilot] specify --dry-run or --run; see --help.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    sys.exit(main())
