"""Real-format fake credentials, generated at run time.

Each value has the exact shape the provider issues (prefix, alphabet, length,
checksum-free) and the entropy gitleaks requires, but is drawn from a seeded
PRNG: nothing here is a live credential, and no value is ever written into
the repository (so the repository's own secret scan stays clean).

Shapes follow the vendored gitleaks v8.30.1 rules named in ``SAMPLES``.
``NEGATIVES`` are strings that must survive the gate unchanged (content
hashes, UUIDs, paths, identifiers): the false-positive side of the corpus.

source: ADR-1110"""

from __future__ import annotations

import json
import random
import string
from typing import NamedTuple

_ALNUM = string.ascii_letters + string.digits
_B32 = string.ascii_uppercase + "234567"


def _draw(rng: random.Random, alphabet: str, n: int) -> str:
    return "".join(rng.choice(alphabet) for _ in range(n))


def _pem_armor(edge: str) -> str:
    """A PEM armor line, assembled so the source holds no key header: the
    repository's scanners (gitleaks, the HOL plugin scanner) read a literal
    header followed by a key body as a committed private key."""
    label = " ".join(("RSA", "PRIVATE", "KEY"))
    return f"{'-' * 5}{edge} {label}{'-' * 5}"


def samples(seed: int = 20261021) -> dict[str, tuple[str, str]]:
    """rule id -> (text containing one secret, the secret itself)."""
    rng = random.Random(seed)
    a = lambda n: _draw(rng, _ALNUM, n)  # noqa: E731 — local shorthand
    pem_body = "\n".join(_draw(rng, _ALNUM + "+/", 64) for _ in range(6))
    values = {
        "github-pat": "ghp_" + a(36),
        "github-fine-grained-pat": "github_pat_" + a(22) + "_" + a(59),
        "github-oauth": "gho_" + a(36),
        "github-app-token": "ghs_" + a(36),
        "github-refresh-token": "ghr_" + a(36),
        "anthropic-api-key": "sk-ant-api03-" + a(93) + "AA",
        "anthropic-admin-api-key": "sk-ant-admin01-" + a(93) + "AA",
        "openai-api-key": "sk-proj-" + a(74) + "T3BlbkFJ" + a(74),
        "jwt": "eyJ" + a(30) + ".eyJ" + a(40) + "." + a(43),
        "aws-access-token": "AKIA" + _draw(rng, _B32, 16),
        "slack-bot-token": "xoxb-"
        + _draw(rng, string.digits, 12)
        + "-"
        + _draw(rng, string.digits, 12)
        + "-"
        + a(24),
        "stripe-access-token": "sk_" + "live_" + a(24),
        "gcp-api-key": "AIza" + a(35),
        "private-key": _pem_armor("BEGIN") + "\n" + pem_body + "\n" + _pem_armor("END"),
        "generic-api-key": a(32),
    }
    texts = {
        rule: f"deploy step: export TOKEN_VALUE={value}\nnext line"
        for rule, value in values.items()
    }
    # the value JSON-quoted: config: api_key = "<value>"
    texts["generic-api-key"] = (
        f"config: api_key = {json.dumps(values['generic-api-key'])}"
    )
    texts["private-key"] = f"key file follows\n{values['private-key']}\n"
    return {rule: (texts[rule], values[rule]) for rule in values}


class Sample(NamedTuple):
    """One corpus entry: a text holding a fake credential, and the value."""

    text: str
    value: str


def sample(rule_id: str, seed: int = 20261021) -> Sample:
    """The corpus entry for one gitleaks rule id.

    Tests take fixtures through this call rather than by subscripting the
    dict with a literal rule id: a literal such as ``"anthropic-api-key"``
    used as a key marks the value as a user's password for CodeQL's
    sensitive-data heuristic, and these values are generated fakes."""
    return Sample(*samples(seed)[rule_id])


NEGATIVES = (
    "content_hash=9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08",
    "memory 3fa85f64-5717-4562-b3fc-2c963f66afa6 promoted to semantic",
    "/Users/someone/Developments/Cortex/mcp_server/shared/redaction_engine.py",
    "def compile_rule_set(doc: Mapping) -> RuleSet:",
    "commit df3a4479 ci(dependabot): watch composite actions",
    "model sentence-transformers/all-MiniLM-L6-v2 revision c9745ed1",
    "Recall@10 = 0.982 on LongMemEval-S (500 questions)",
)
