"""Audit a proposed raw-character prefix; never changes production encoding.

Run with --snapshot pointing to a cached model snapshot and --cap explicitly
supplied. Default mode uses only tokenizers (no torch, model, DB or network).
--model additionally measures real uncached EmbeddingEngine.encode bytes and
timings on CPU. A token mismatch disproves token preservation; actual vector
differences are reported only when --model is explicitly requested.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import sys
from pathlib import Path

from scripts.embedding_prefix_fixtures import fixtures


def load_tokenizer(snapshot: Path):
    from tokenizers import Tokenizer  # noqa: PLC0415 — audit-only optional dependency; never loads a neural model

    config = json.loads((snapshot / "sentence_bert_config.json").read_text())
    raw = json.loads((snapshot / "tokenizer.json").read_text())
    tokenizer = Tokenizer.from_file(str(snapshot / "tokenizer.json"))
    # source: ADR-0762
    tokenizer.no_padding()
    tokenizer.enable_truncation(
        max_length=config["max_seq_length"], strategy="longest_first", direction="right"
    )
    return tokenizer, raw, config


def signature(encoding):
    """All model input arrays, not just the visible token strings."""
    return encoding.ids, encoding.type_ids, encoding.attention_mask


def token_report(tokenizer, text: str, cap: int) -> dict:
    before, after = tokenizer.encode(text), tokenizer.encode(text[:cap])
    end = max(
        (
            end
            for (_, end), special in zip(
                before.offsets, before.special_tokens_mask, strict=True
            )
            if not special
        ),
        default=0,
    )
    return {
        "chars": len(text),
        "sha256": hashlib.sha256(text.encode()).hexdigest(),
        "candidate_chars": len(text[:cap]),
        "model_inputs_equal": signature(before) == signature(after),
        "tokens_before": len(before.ids),
        "tokens_after": len(after.ids),
        "ids_before": before.ids,
        "ids_after": after.ids,
        # This offset is an observation, not a safe cap: cutting within a
        # WordPiece word can change its earlier tokens or UNK classification.
        "furthest_retained_token_end_not_safe_cap": end,
    }


def corpus_cases(path: Path | None) -> dict[str, str]:
    """Optional local JSONL: one {name, text} object per line, read only."""
    if path is None:
        return {}
    result = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            item = json.loads(line)
            name, text = item["name"], item["text"]
            if not isinstance(name, str) or not isinstance(text, str):
                raise ValueError("corpus name and text must be strings")
            if name in result:
                raise ValueError(f"duplicate corpus name: {name}")
            result[name] = text
    return result


def metadata(snapshot: Path, config: dict) -> dict:
    names = ("tokenizer.json", "sentence_bert_config.json", "tokenizer_config.json")
    return {
        "python": sys.version,
        "platform": platform.platform(),
        "snapshot": str(snapshot.resolve()),
        "config_sha256": {
            name: hashlib.sha256((snapshot / name).read_bytes()).hexdigest()
            for name in names
        },
        "packages": package_versions(),
        "model_sequence_limit": config["max_seq_length"],
        "sentence_transformer_do_lower_case": config.get("do_lower_case"),
    }


def package_versions() -> dict:
    result = {}
    for name in ("tokenizers", "sentence-transformers", "transformers"):
        try:
            result[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            result[name] = None
    return result


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--cap", type=int, required=True)
    parser.add_argument("--corpus-jsonl", type=Path)
    parser.add_argument(
        "--case", action="append", help="Only these fixture/corpus names"
    )
    parser.add_argument(
        "--model", action="store_true", help="Explicitly load real CPU model"
    )
    args = parser.parse_args()
    if args.cap < 1:
        parser.error(
            "--cap must be positive; no default or empirical margin is assumed"
        )
    return args


def main() -> None:
    args = arguments()
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    tokenizer, raw, config = load_tokenizer(args.snapshot)
    cases = fixtures(raw["model"]["max_input_chars_per_word"])
    cases.update(
        {f"corpus:{key}": text for key, text in corpus_cases(args.corpus_jsonl).items()}
    )
    if args.case:
        cases = {name: cases[name] for name in args.case}
    rows = {
        name: token_report(tokenizer, text, args.cap) for name, text in cases.items()
    }
    report = {
        "metadata": metadata(args.snapshot, config),
        "cap_under_audit": args.cap,
        "tokenizer": {key: raw[key] for key in ("normalizer", "pre_tokenizer")},
        "word_limit": raw["model"]["max_input_chars_per_word"],
        "tokens": rows,
        "preserves_fixture_model_inputs": all(
            row["model_inputs_equal"] for row in rows.values()
        ),
        "universal_character_cap_proven": False,
    }
    if args.model:
        from scripts.embedding_prefix_model_measure import measure_model  # noqa: PLC0415 — model inference is opt-in, never imported by token-only audit

        report["real_model"] = measure_model(args.snapshot, cases, args.cap)
    else:
        report["torch_loaded"] = "torch" in sys.modules
        report["sentence_transformers_loaded"] = "sentence_transformers" in sys.modules
        assert not report["torch_loaded"] and not report["sentence_transformers_loaded"]
    print(json.dumps(report, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()
