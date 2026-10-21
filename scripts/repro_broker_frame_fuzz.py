#!/usr/bin/env python3
"""ADR-1112 increment 3: the broker frame decoder under mutation, one command.

    python scripts/repro_broker_frame_fuzz.py [--inputs 200000] [--seed 1112]

atheris (the coverage-guided engine CI's ClusterFuzzLite job uses on
``fuzz/fuzz_broker_frame.py``) publishes no macOS or aarch64 wheel, so this
runs the same harness property locally with a deterministic mutator: byte
flips, insertions, deletions and splices of the committed corpus, plus
generated JSON trees that use every codec tag with random fields. It counts
inputs refused with ``ProtocolError``, inputs accepted, and escapes (any
other exception, which is a bug); it appends the counts to the experiment
log and exits 1 on any escape.

source: ADR-1112 (research protocol); ADR-0881 (corpus replay)
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fuzz.fuzz_broker_frame import consume  # noqa: E402
from mcp_server.infrastructure.broker_protocol import ProtocolError, loads  # noqa: E402

CORPUS = ROOT / "fuzz" / "corpus" / "fuzz_broker_frame"
LOG = ROOT / "docs" / "verification" / "connection-broker" / "experiment-log.md"
# source: broker_codec._decode_tagged (every tag the decoder knows, plus unknown)
TAGS = (
    "tuple",
    "set",
    "dict",
    "dt",
    "date",
    "td",
    "dec",
    "uuid",
    "b",
    "nd",
    "rec",
    "x",
)
# source: ADR-1112 generator shape: leaf share, then tagged vs list nodes
LEAF_SHARE = 0.3
# source: same generator
TAGGED_SHARE = 0.5
# source: ADR-1112 mutation kinds: flip, insert, delete, splice
FLIP, INSERT, DELETE = 0, 1, 2
SCALARS = (None, True, 0, -1, 2**63, 1.5, float("inf"), "", "a", "AA==", [], {})


def _tree(rng: random.Random, depth: int):
    if depth <= 0 or rng.random() < LEAF_SHARE:
        return rng.choice(SCALARS)
    if rng.random() < TAGGED_SHARE:
        node = {"__t": rng.choice(TAGS)}
        for key in rng.sample(["v", "dtype", "shape", "cls"], rng.randint(0, 4)):
            node[key] = _tree(rng, depth - 1)
        return node
    return [_tree(rng, depth - 1) for _ in range(rng.randint(0, 3))]


def _generated(rng: random.Random) -> bytes:
    message = {"t": rng.choice(["req", "res", "hello", 7]), "x": _tree(rng, 4)}
    return json.dumps(message).encode()


def _mutated(rng: random.Random, seeds: list[bytes]) -> bytes:
    data = bytearray(rng.choice(seeds))
    for _ in range(rng.randint(1, 8)):
        op = rng.randrange(4)
        position = rng.randrange(len(data) + 1)
        if op == FLIP and data:
            data[min(position, len(data) - 1)] ^= 1 << rng.randrange(8)
        elif op == INSERT:
            data[position:position] = bytes([rng.randrange(256)])
        elif op == DELETE and data:
            del data[position : position + rng.randint(1, 8)]
        else:
            other = rng.choice(seeds)
            start = rng.randrange(len(other))
            data[position:position] = other[start : start + rng.randint(1, 32)]
    return bytes(data)


def run(inputs: int, seed: int) -> dict:
    rng = random.Random(seed)
    seeds = [path.read_bytes() for path in sorted(CORPUS.iterdir())]
    counts = {"inputs": inputs, "refused": 0, "accepted": 0, "escapes": 0}
    first_escape = None
    started = time.monotonic()
    for index in range(inputs):
        data = _generated(rng) if index % 2 else _mutated(rng, seeds)
        try:
            consume(data)  # the harness property: only ProtocolError is a refusal
            loads(data)
            counts["accepted"] += 1
        except ProtocolError:
            counts["refused"] += 1
        except Exception as exc:  # noqa: BLE001 — every escape is counted and reported
            counts["escapes"] += 1
            if first_escape is None:
                first_escape = f"{type(exc).__name__}: {exc} on {data[:200]!r}"
    counts["seconds"] = round(time.monotonic() - started, 1)
    counts["first_escape"] = first_escape
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=int, default=200_000)
    parser.add_argument("--seed", type=int, default=1112)
    parser.add_argument("--no-log", action="store_true")
    args = parser.parse_args()
    counts = run(args.inputs, args.seed)
    print(json.dumps(counts, indent=2))
    if not args.no_log:
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
        with LOG.open("a", encoding="utf-8") as stream:
            stream.write(
                f"\n### broker frame fuzz {stamp} "
                f"(`python scripts/repro_broker_frame_fuzz.py --seed {args.seed}`)\n\n"
                f"- `{json.dumps(counts)}`\n"
            )
    return 1 if counts["escapes"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
