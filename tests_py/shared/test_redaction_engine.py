"""The detector behind the redaction gate (ADR-1110).

Corpus: real-format fake credentials generated at run time
(``scripts/secret_corpus.py``); one case per provider shape the audit named
(GitHub, Anthropic, OpenAI, JWT) plus AWS, Slack, Stripe, GCP, PEM and the
keyword-anchored generic rule. Parity of this port with the gitleaks binary is
checked in CI by ``scripts/redaction_parity.py``.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from mcp_server.shared.redaction_engine import (
    REDACTION_PREFIX,
    redaction_spans,
    shannon_entropy,
)
from mcp_server.shared.redaction_gate import RULES_PATH, redact_text, rule_set
from scripts.secret_corpus import NEGATIVES, sample, samples

REPO = Path(__file__).resolve().parents[2]
VENDOR = REPO / "third_party" / "gitleaks" / "v8.30.1"
CORPUS = samples()


@pytest.mark.parametrize("rule_id", sorted(CORPUS))
def test_each_provider_shape_is_detected_by_its_own_rule(rule_id):
    text, fake = CORPUS[rule_id]
    found = {r for _s, _e, r in redaction_spans(text, rule_set())}
    assert rule_id in found


@pytest.mark.parametrize("rule_id", sorted(CORPUS))
def test_each_provider_secret_is_gone_after_the_gate(rule_id):
    text, fake = CORPUS[rule_id]
    redacted = redact_text(text)
    assert fake not in redacted
    assert f"{REDACTION_PREFIX}" in redacted


def test_the_audit_probe_shapes_are_all_redacted_now():
    """E16 of the 2026-10-21 audit: GitHub, Anthropic, OpenAI and JWT were kept
    by the old scrubber. Every one of them is redacted by the gate."""
    for rule_id in ("github-pat", "anthropic-api-key", "openai-api-key", "jwt"):
        text, fake = CORPUS[rule_id]
        assert fake not in redact_text(text), rule_id


@pytest.mark.parametrize("text", NEGATIVES)
def test_hashes_ids_paths_and_code_are_left_alone(text):
    assert redact_text(text) == text


def test_redaction_is_idempotent():
    blob = "\n".join(t for t, _s in CORPUS.values())
    once = redact_text(blob)
    assert redact_text(once) == once


def test_low_entropy_lookalike_is_not_a_secret():
    """gitleaks drops a match whose entropy is <= the rule's threshold."""
    lookalike = "ghp_" + "ab" * 18
    assert shannon_entropy(lookalike[4:]) <= 3.0
    assert redact_text(f"token {lookalike}") == f"token {lookalike}"


def test_global_allowlist_keeps_placeholders():
    """An env-var placeholder is not a secret (gitleaks global allowlist).

    The full gate still masks it: Cortex's own ``key=value`` shape (ADR-0663)
    is stricter than gitleaks and has no allowlist."""
    text = 'api_key = "${API_KEY}"'
    assert redaction_spans(text, rule_set()) == []


def test_a_marker_left_by_the_gitleaks_pass_is_not_rewritten():
    text, _fake = sample("generic-api-key")
    assert "[REDACTED:generic-api-key]" in redact_text(text)


def test_cortex_local_shapes_still_apply():
    """URL passwords and password= assignments, which gitleaks has no rule for."""
    url = "postgresql://cortex:" + "Hunter2Hunter2" + "@db:5432/cortex"
    assert "Hunter2Hunter2" not in redact_text(f"connect {url}")
    assert "Hunter2Hunter2" not in redact_text("password=" + "Hunter2Hunter2")


def test_vendored_rule_file_is_the_pinned_upstream_file():
    provenance = json.loads((VENDOR / "PROVENANCE.json").read_text())
    digest = hashlib.sha256((VENDOR / "gitleaks.toml").read_bytes()).hexdigest()
    assert digest == provenance["sha256"]
    assert provenance["version"] == "8.30.1"
    assert json.loads(RULES_PATH.read_text())["source"] == provenance


def test_the_rules_the_gate_relies_on_were_all_translated():
    doc = json.loads(RULES_PATH.read_text())
    translated = {r["id"] for r in doc["rules"]}
    required = set(CORPUS) | {"jwt-base64", "aws-amazon-bedrock-api-key-long-lived"}
    assert required <= translated
    # the only rule not applied needs a file name, which stored text has not
    assert sorted(s["id"] for s in doc["skipped"]) == [
        "freemius-secret-key",
        "hashicorp-tf-password",
        "kubernetes-secret-yaml",
        "nuget-config-password",
        "pkcs12-file",
    ]
    assert len(doc["rules"]) == 217


@pytest.mark.skipif(sys.version_info < (3, 11), reason="tomllib is 3.11+")
def test_committed_rules_are_a_fresh_translation_of_the_vendored_file():
    from scripts.vendor_gitleaks_rules import OUTPUT, build, render

    assert OUTPUT.read_text(encoding="utf-8") == render(build())


@pytest.mark.parametrize(
    ("re2", "python"),
    [
        (r"p8e-(?i)[a-z0-9]{32}", r"p8e-(?i:[a-z0-9]{32})"),
        (r"\b(LTAI(?i)[a-z0-9]{20})\b", r"\b(LTAI(?i:[a-z0-9]{20}))\b"),
        (r"(x(?i)a|b)", r"(x(?i:a)|(?i:b))"),
        (r"\b(sha256~[\w-]{43})(?:[^\w-]|\z)", r"\b(sha256~[\w-]{43})(?:[^\w-]|\Z)"),
        (r"\b(pat[[:alnum:]]{14})", r"\b(pat[a-zA-Z0-9]{14})"),
        (r"(?i)leading", r"(?i)leading"),
    ],
)
def test_re2_to_python_translation(re2, python):
    from scripts.vendor_gitleaks_rules import translate

    assert translate(re2) == python


PROVIDERS = sorted(set(CORPUS) - {"generic-api-key", "private-key"})


@pytest.mark.parametrize("rule_id", PROVIDERS)
@pytest.mark.parametrize("follow", [",", ".", ")", "]", ":", "!", "?", '."', ".\n"])
def test_a_key_followed_by_sentence_punctuation_is_still_redacted(rule_id, follow):
    """Six gitleaks rules require whitespace/quote/; after the key; the gate's
    prose pass (ADR-1110) closes that gap for text written as sentences."""
    _text, fake = CORPUS[rule_id]
    for context in (f"the key {fake}{follow} next", f'["note {fake}{follow}"]'):
        assert fake not in redact_text(context), (rule_id, follow, context[:12])
