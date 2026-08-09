"""Adversarial arm of the trust-factor calibration (issue #368).

Pre-registration, decision rule and grid:
`docs/provenance/trust-factor-calibration.md`.

The decision rule has two members: "defends 4/4 adversarial scenarios" and
"every gated floor still holds". The floors are measured by the expensive arm
(`benchmarks/trust_factor_sweep.sh`, one `reproduce.sh` per cell). This module
measures the first member — which is cheap (SQLite, in-memory, seconds per
point) and, until this file existed, was the only half of the rule with no
committed artefact behind it: the §Grid table was carried in prose alone.

Montage is the one already asserted by
`tests_py/infrastructure/test_sqlite_trust_ranking.py` — same corpus, same
embedding construction, same recall entry point — so this sweep and that suite
argue about the same passages. A scenario counts as DEFENDED when both
memories are retrieved and the legitimate one outranks the adversarial one:
a demotion, not a filter.

    python -m benchmarks.lib.trust_factor_sweep [OUT_DIR]
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from benchmarks.lib.adversarial_corpus import (
    AdversarialPair,
    all_pairs,
    memory_payloads,
)
from mcp_server.core.capture_origin import trusted_origins_at_read
from mcp_server.infrastructure.sqlite_store import SqliteMemoryStore

_DIM = 384
_DOMAIN = "trust-factor-adversarial-sweep"

# source: docs/provenance/trust-factor-calibration.md §Grid — the prose table
# it reports (1.0 -> 0/4, 0.95-0.80 -> 2/4, 0.70-0.20 -> 4/4) is stated over
# these points, so the sweep re-measures exactly them and can confirm or
# refute the table rather than sampling somewhere else.
GRID: tuple[float, ...] = (
    1.0,
    0.95,
    0.9,
    0.85,
    0.8,
    0.75,
    0.7,
    0.6,
    0.5,
    0.4,
    0.3,
    0.2,
)

_DEFAULT_OUT = Path("benchmarks/results/trust-factor-sweep/adversarial")


def _aligned(similarity: float, seed: int) -> bytes:
    """384-dim unit vector at `similarity` cosine to the query direction.

    Same Gram-Schmidt construction as the two trust-ranking test modules,
    restated here for the same reason they restate it from each other: those
    helpers are bound to test modules that skip under conditions which do not
    apply to this sweep.
    """
    rng0 = np.random.default_rng(0)
    base = rng0.standard_normal(_DIM).astype(np.float32)
    base /= np.linalg.norm(base)
    if similarity >= 1.0:
        return base.tobytes()
    rng = np.random.default_rng(seed)
    other = rng.standard_normal(_DIM).astype(np.float32)
    other -= other.dot(base) * base
    other /= np.linalg.norm(other)
    mixed = similarity * base + np.sqrt(max(0.0, 1.0 - similarity**2)) * other
    return mixed.astype(np.float32).tobytes()


def _seed(store: SqliteMemoryStore, pair: AdversarialPair) -> None:
    legitimate, adversarial = memory_payloads(pair, _DOMAIN)
    legitimate["embedding"] = _aligned(pair.legitimate_similarity, 11)
    adversarial["embedding"] = _aligned(pair.adversarial_similarity, 12)
    store.insert_memory(legitimate)
    store.insert_memory(adversarial)


def evaluate(pair: AdversarialPair, factor: float) -> dict:
    """Run one (scenario, W) point on a throwaway in-memory store.

    Post: `defended` is True only when BOTH memories came back and the
    legitimate one ranks ahead. A missing adversarial entry is reported as
    `retrieved_adversarial: false` and NOT counted as a defence — a filtered
    attacker is a different mechanism than a demoted one, and the pre-
    registration asks about demotion.
    """
    store = SqliteMemoryStore()
    try:
        _seed(store, pair)
        rows = store.recall_memories(
            query_text=pair.query,
            query_embedding=_aligned(1.0, 0),
            intent="general",
            domain=_DOMAIN,
            min_heat=0.0,
            max_results=10,
            trusted_origins=trusted_origins_at_read(),
            untrusted_factor=factor,
        )
    finally:
        store.close()

    contents = [r["content"] for r in rows]
    has_legit = pair.legitimate in contents
    has_adv = pair.adversarial in contents
    defended = (
        has_legit
        and has_adv
        and contents.index(pair.legitimate) < contents.index(pair.adversarial)
    )
    return {
        "scenario": pair.scenario,
        "retrieved_legitimate": has_legit,
        "retrieved_adversarial": has_adv,
        "defended": defended,
    }


def sweep(grid: tuple[float, ...] = GRID) -> list[dict]:
    pairs = all_pairs()
    out = []
    for w in grid:
        points = [evaluate(p, w) for p in pairs]
        defended = sum(1 for p in points if p["defended"])
        out.append(
            {
                "W": w,
                "defended": defended,
                "total": len(pairs),
                "scenarios": points,
            }
        )
        print(f"W={w:<5} {defended}/{len(pairs)} defended")
    return out


def _git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except (subprocess.CalledProcessError, OSError):
        return "unknown"


def main(argv: list[str]) -> int:
    out_dir = Path(argv[1]) if len(argv) > 1 else _DEFAULT_OUT
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = sweep()
    payload = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "git_sha": _git_sha(),
        "python": platform.python_version(),
        "numpy": np.__version__,
        "backend": "sqlite (in-memory)",
        "corpus": "benchmarks/lib/adversarial_corpus.py",
        "trusted_origins": list(trusted_origins_at_read()),
        "grid": list(GRID),
        "results": rows,
    }
    dest = out_dir / "adversarial-sweep.json"
    dest.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"\nwritten: {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
