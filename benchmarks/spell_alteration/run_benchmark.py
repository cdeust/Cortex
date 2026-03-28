"""Harry Potter spell alteration benchmark — 1.5M token haystack.

Two tests of increasing difficulty:

TEST A (Easy): Ingest the full story with 2 fake spells injected among
the real ones. The system must identify which spells are fake by
recalling them from 3000+ memories.

TEST B (Hard): Ingest the ORIGINAL story first (all real spells). Then
ingest the ALTERED version (2 spells replaced). The system must compare
both versions from memory and identify which originals were replaced
and by which fakes.

Run:
    python3 benchmarks/spell_alteration/run_benchmark.py --pdf /tmp/harrypotter.pdf
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from pathlib import Path

os.environ["PYTORCH_ENABLE_MPS_FALLBACK"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from benchmarks.lib.bench_db import BenchmarkDB

CHUNK_SIZE = 2000
DOMAIN_ORIGINAL = "hp-original"
DOMAIN_ALTERED = "hp-altered"

KNOWN_REAL_SPELLS = [
    "Accio",
    "Expecto Patronum",
    "Expelliarmus",
    "Stupefy",
    "Lumos",
    "Riddikulus",
    "Crucio",
    "Imperio",
    "Avada Kedavra",
    "Protego",
    "Impedimenta",
    "Sectumsempra",
    "Muffliato",
    "Reparo",
    "Petrificus Totalus",
    "Reducto",
    "Alohomora",
    "Silencio",
    "Wingardium Leviosa",
    "Obliviate",
    "Incendio",
    "Diffindo",
]

FAKE_NAMES = ["Veritanox", "Crepusculum"]


# ── Helpers ───────────────────────────────────────────────────────────────


def extract_text(pdf_path: str) -> str:
    """Extract full text from PDF."""
    import pymupdf

    doc = pymupdf.open(pdf_path)
    return "".join(page.get_text() for page in doc)


def chunk_text(text: str) -> list[str]:
    """Split text into sentence-boundary chunks."""
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + CHUNK_SIZE, len(text))
        if end < len(text):
            for sep in (". ", ".\n", "! ", "? "):
                last = text.rfind(sep, start, end)
                if last > start + CHUNK_SIZE // 2:
                    end = last + len(sep)
                    break
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start = end
    return chunks


def replace_spells(
    text: str,
    targets: list[str],
    fakes: list[str],
) -> tuple[str, dict[str, str]]:
    """Replace target spell names with fakes. Returns (text, map)."""
    mapping: dict[str, str] = {}
    for orig, fake in zip(targets, fakes):
        mapping[orig] = fake
        text = re.sub(re.escape(orig), fake, text, flags=re.IGNORECASE)
    return text, mapping


def find_spells_in_text(text: str, spells: list[str]) -> dict[str, int]:
    """Count each spell's occurrences."""
    return {
        s: len(re.findall(re.escape(s), text, re.IGNORECASE))
        for s in spells
        if re.search(re.escape(s), text, re.IGNORECASE)
    }


def store_corpus(db: BenchmarkDB, chunks: list[str], domain: str) -> int:
    """Store text chunks as memories. Returns count."""
    memories = [
        {
            "content": chunk,
            "created_at": None,
            "heat": 0.5,
            "source": f"{domain}-{i}",
            "tags": [domain, f"chunk:{i}"],
        }
        for i, chunk in enumerate(chunks)
    ]
    ids, _ = db.load_memories(memories, domain=domain)
    return len(ids)


# ── TEST A: Spot the fakes ────────────────────────────────────────────────


def test_a_spot_the_fakes(db: BenchmarkDB, mapping: dict[str, str]) -> dict:
    """Ingest altered story. Can the system find the 2 fake spells?"""
    print("\n" + "=" * 60)
    print("TEST A: Spot the fake spells in the altered story")
    print("=" * 60)
    print("  Query: recall all spell names from the story")
    print(f"  Haystack: {DOMAIN_ALTERED} memories")
    print()

    # Query for every known spell + the fakes
    all_candidates = KNOWN_REAL_SPELLS + FAKE_NAMES
    found_spells: dict[str, bool] = {}

    for spell in all_candidates:
        results = db.recall(f'"{spell}"', top_k=5, domain=DOMAIN_ALTERED)
        contents = [r.get("content", "") for r in results]
        found = any(spell in c for c in contents)
        found_spells[spell] = found

    # The 2 fakes should be found
    fakes_found = [FAKE_NAMES[i] for i in range(2) if found_spells.get(FAKE_NAMES[i])]
    # The 2 replaced originals should NOT be found
    replaced_originals = list(mapping.keys())
    originals_absent = [
        orig for orig in replaced_originals if not found_spells.get(orig)
    ]

    t_a1 = len(fakes_found) == 2
    t_a2 = len(originals_absent) == 2

    print(f"  Fake spells found: {fakes_found} — {'PASS' if t_a1 else 'FAIL'}")
    print(f"  Originals absent:  {originals_absent} — {'PASS' if t_a2 else 'FAIL'}")

    # How many real spells still found?
    unaltered = [s for s in KNOWN_REAL_SPELLS if s not in mapping]
    still_found = sum(1 for s in unaltered if found_spells.get(s))
    print(f"  Unaltered spells:  {still_found}/{len(unaltered)} retrievable")

    return {
        "fakes_found": t_a1,
        "originals_absent": t_a2,
        "unaltered_recall": still_found / len(unaltered) if unaltered else 0,
    }


# ── TEST B: Compare and identify replacements ────────────────────────────


def _match_context_to_fake(
    db: BenchmarkDB,
    context_query: str,
    candidates: list[str],
    claimed: set[str],
) -> str | None:
    """Find which fake spell appears in the altered passage matching context."""
    results = db.recall(context_query, top_k=5, domain=DOMAIN_ALTERED)
    contents = " ".join(r.get("content", "") for r in results)
    # Score each unclaimed fake by how many times it appears in context results
    scores: dict[str, int] = {}
    for fake in candidates:
        if fake in claimed:
            continue
        scores[fake] = contents.count(fake)
    if not scores:
        return None
    best = max(scores, key=lambda k: scores[k])
    return best if scores[best] > 0 else None


def test_b_compare_versions(
    db: BenchmarkDB,
    mapping: dict[str, str],
) -> dict:
    """Both versions stored. Identify which originals map to which fakes."""
    print("\n" + "=" * 60)
    print("TEST B: Compare original and altered — identify replacements")
    print("=" * 60)
    print("  Both versions in memory. Which spell was replaced by which?")
    print()

    # Step 1: Find all spells in original
    original_spells: dict[str, int] = {}
    for spell in KNOWN_REAL_SPELLS:
        results = db.recall(f'"{spell}"', top_k=3, domain=DOMAIN_ORIGINAL)
        count = sum(1 for r in results if spell in r.get("content", ""))
        if count > 0:
            original_spells[spell] = count

    # Step 2: Find all spells in altered
    altered_spells: dict[str, int] = {}
    for spell in KNOWN_REAL_SPELLS + FAKE_NAMES:
        results = db.recall(f'"{spell}"', top_k=3, domain=DOMAIN_ALTERED)
        count = sum(1 for r in results if spell in r.get("content", ""))
        if count > 0:
            altered_spells[spell] = count

    # Step 3: Diff — spells in original but not altered = replaced
    missing_from_altered = [s for s in original_spells if s not in altered_spells]
    # New in altered = the fakes
    new_in_altered = [s for s in altered_spells if s not in original_spells]

    print(f"  Original spells found:  {len(original_spells)}")
    print(f"  Altered spells found:   {len(altered_spells)}")
    print(f"  Missing from altered:   {missing_from_altered}")
    print(f"  New in altered:         {new_in_altered}")

    # Step 4: Match by context — find which fake occupies the same passages
    detected_mapping: dict[str, str] = {}
    claimed_fakes: set[str] = set()

    for orig in missing_from_altered:
        orig_results = db.recall(f'"{orig}"', top_k=3, domain=DOMAIN_ORIGINAL)
        if not orig_results:
            continue
        # Extract surrounding context words (strip the spell name)
        context = orig_results[0].get("content", "")
        # Get ~80 chars around the first spell mention
        idx = context.find(orig)
        if idx < 0:
            continue
        start = max(0, idx - 40)
        end = min(len(context), idx + len(orig) + 40)
        window = context[start:end].replace(orig, "").strip()
        # Keep only meaningful context words (3+ chars)
        words = [w for w in re.split(r"\W+", window) if len(w) >= 3]
        context_query = " ".join(words[:8])

        # Search altered corpus with this context
        best_fake = _match_context_to_fake(
            db,
            context_query,
            new_in_altered,
            claimed_fakes,
        )
        if best_fake:
            detected_mapping[orig] = best_fake
            claimed_fakes.add(best_fake)

    print("\n  Detected mapping:")
    for orig, fake in detected_mapping.items():
        correct = mapping.get(orig) == fake
        print(f"    {orig} -> {fake} {'CORRECT' if correct else 'WRONG'}")

    # Score
    correct_pairs = sum(
        1 for orig, fake in detected_mapping.items() if mapping.get(orig) == fake
    )
    identified_missing = set(missing_from_altered) == set(mapping.keys())
    identified_fakes = set(new_in_altered) >= set(mapping.values())

    t_b1 = identified_missing
    t_b2 = identified_fakes
    t_b3 = correct_pairs == len(mapping)

    print(f"\n  Identified removed spells: {'PASS' if t_b1 else 'FAIL'}")
    print(f"  Identified fake spells:    {'PASS' if t_b2 else 'FAIL'}")
    print(
        f"  Correct pairings:          {correct_pairs}/{len(mapping)} {'PASS' if t_b3 else 'FAIL'}"
    )

    return {
        "identified_missing": t_b1,
        "identified_fakes": t_b2,
        "correct_pairings": t_b3,
        "detected_mapping": detected_mapping,
    }


# ── Main ──────────────────────────────────────────────────────────────────


def run_benchmark(pdf_path: str, seed: int = 42) -> dict:
    """Run both tests."""
    print(f"Extracting text from {pdf_path}...")
    full_text = extract_text(pdf_path)
    print(f"  {len(full_text):,} chars ({len(full_text) // 4:,} est. tokens)")

    # Pick 2 spells to replace
    rng = random.Random(seed)
    eligible = [
        s
        for s in KNOWN_REAL_SPELLS
        if len(re.findall(re.escape(s), full_text, re.IGNORECASE)) >= 10
    ]
    targets = rng.sample(eligible, 2)

    for i, t in enumerate(targets):
        n = len(re.findall(re.escape(t), full_text, re.IGNORECASE))
        print(f"  Replace: {t} ({n}x) -> {FAKE_NAMES[i]}")

    altered_text, mapping = replace_spells(full_text, targets, FAKE_NAMES)

    original_chunks = chunk_text(full_text)
    altered_chunks = chunk_text(altered_text)
    print(f"\n  Original chunks: {len(original_chunks)}")
    print(f"  Altered chunks:  {len(altered_chunks)}")

    t0 = time.monotonic()

    with BenchmarkDB() as db:
        db.clear()

        print("\nStoring original story...")
        n1 = store_corpus(db, original_chunks, DOMAIN_ORIGINAL)
        print(f"  {n1} memories stored")

        print("Storing altered story...")
        n2 = store_corpus(db, altered_chunks, DOMAIN_ALTERED)
        print(f"  {n2} memories stored")
        print(f"  Total: {n1 + n2} memories ({(len(full_text) * 2) // 4:,} tokens)")

        store_time = time.monotonic() - t0
        print(f"  Store time: {store_time:.1f}s")

        # Run tests
        result_a = test_a_spot_the_fakes(db, mapping)
        result_b = test_b_compare_versions(db, mapping)

    total = time.monotonic() - t0

    # Summary
    print("\n" + "=" * 60)
    print("FINAL RESULTS")
    print("=" * 60)

    tests = {
        "A1 — Fake spells retrievable": result_a["fakes_found"],
        "A2 — Original spells absent": result_a["originals_absent"],
        "B1 — Identified removed spells": result_b["identified_missing"],
        "B2 — Identified fake spells": result_b["identified_fakes"],
        "B3 — Correct orig->fake pairing": result_b["correct_pairings"],
    }

    for name, passed in tests.items():
        print(f"  {'PASS' if passed else 'FAIL'} | {name}")

    all_pass = all(tests.values())
    print(f"\n  Haystack: {n1 + n2} memories (~{(len(full_text) * 2) // 4:,} tokens)")
    print(f"  Mapping: {mapping}")
    print(f"  Total time: {total:.1f}s")
    print(f"  VERDICT: {'ALL PASS' if all_pass else 'FAILURES DETECTED'}")

    return {
        "all_pass": all_pass,
        "tests": tests,
        "mapping": mapping,
        "detected_mapping": result_b.get("detected_mapping", {}),
        "haystack_memories": n1 + n2,
        "total_time_s": round(total, 2),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", default="/tmp/harrypotter.pdf")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    if not Path(args.pdf).exists():
        print(f"PDF not found: {args.pdf}")
        sys.exit(1)

    results = run_benchmark(args.pdf, seed=args.seed)
    print(json.dumps(results, indent=2))
