"""Pure secret detector: a port of gitleaks' per-rule decision procedure.

The rule set is data (the vendored gitleaks default config, translated by
``scripts/vendor_gitleaks_rules.py``); this module only applies it. For each
rule, in gitleaks v8.30.1 order (``detect/detect.go`` ``detectRule`` and
``checkFindingAllowed``, ``config/allowlist.go``):

1. keyword prefilter: the rule runs only if one of its keywords occurs in the
   lowercased text (a rule without keywords always runs);
2. every regex match yields a secret: the ``secretGroup`` capture when set,
   else the first non-empty capture group, else the whole match;
3. a rule with an ``entropy`` threshold drops a secret whose Shannon entropy
   (bits per character) is ``<=`` the threshold;
4. the global allowlist, then the rule's allowlists, drop a secret when a
   regex matches its target (``secret``, ``match`` or ``line``) or the secret
   contains a stopword; ``AND`` allowlists need every configured check, and a
   path check can never pass here because stored text has no file name.

Not ported: gitleaks' decoding passes (base64/hex/percent re-scan) and
multi-part ``required`` rules (none in the pinned default set).

Redaction replaces each secret span with ``[REDACTED:<rule-id>]``; overlapping
spans are merged. The marker contains no character any rule's value class
accepts, so redaction is idempotent.

source: ADR-1110"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

REDACTION_PREFIX = "[REDACTED:"


@dataclass(frozen=True)
class Allowlist:
    condition: str
    target: str
    regexes: tuple[re.Pattern[str], ...]
    stopwords: tuple[str, ...]
    has_paths: bool

    def allows(self, secret: str, match: str, line: str) -> bool:
        target = {"match": match, "line": line}.get(self.target, secret)
        regex_ok = any(r.search(target) for r in self.regexes)
        lowered = secret.lower()
        stop_ok = any(w in lowered for w in self.stopwords)
        if self.condition != "AND":
            return regex_ok or stop_ok
        checks: list[bool] = []
        if self.has_paths:
            checks.append(False)
        if self.regexes:
            checks.append(regex_ok)
        if self.stopwords:
            checks.append(stop_ok)
        return bool(checks) and all(checks)


@dataclass
class Rule:
    rule_id: str
    pattern: str
    secret_group: int
    entropy: float
    keywords: tuple[str, ...]
    allowlists: tuple[Allowlist, ...]
    _compiled: re.Pattern[str] | None = field(default=None, repr=False)

    @property
    def regex(self) -> re.Pattern[str]:
        # Compiled on first keyword hit: a hook process pays only for the
        # rules its text can trigger.
        if self._compiled is None:
            self._compiled = re.compile(self.pattern)
        return self._compiled


@dataclass(frozen=True)
class RuleSet:
    rules: tuple[Rule, ...]
    global_allowlist: Allowlist


def shannon_entropy(text: str) -> float:
    """Shannon entropy in bits per character (gitleaks ``shannonEntropy``)."""
    if not text:
        return 0.0
    n = len(text)
    return -sum(c / n * math.log2(c / n) for c in Counter(text).values())


def _allowlist(raw: Mapping) -> Allowlist:
    return Allowlist(
        condition=str(raw.get("condition", "OR")),
        target=str(raw.get("regex_target", "secret")),
        regexes=tuple(re.compile(r) for r in raw.get("regexes", ())),
        stopwords=tuple(raw.get("stopwords", ())),
        has_paths=bool(raw.get("has_paths", False)),
    )


def compile_rule_set(doc: Mapping) -> RuleSet:
    """Build a RuleSet from the translated rule document."""
    rules = tuple(
        Rule(
            rule_id=r["id"],
            pattern=r["regex"],
            secret_group=int(r.get("secret_group", 0)),
            entropy=float(r.get("entropy", 0.0)),
            keywords=tuple(r.get("keywords", ())),
            allowlists=tuple(_allowlist(a) for a in r.get("allowlists", ())),
        )
        for r in doc["rules"]
    )
    glob = doc.get("global_allowlist", {})
    return RuleSet(rules=rules, global_allowlist=_allowlist(glob))


def _secret_span(m: re.Match[str], secret_group: int) -> tuple[int, int]:
    if m.re.groups and secret_group and secret_group <= m.re.groups:
        return m.span(secret_group)
    for g in range(1, m.re.groups + 1):
        if m.group(g):
            return m.span(g)
    start, end = m.span()
    return start, start + len(m.group(0).rstrip("\n"))


def _line_of(text: str, start: int, end: int) -> str:
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    return text[line_start : len(text) if line_end < 0 else line_end]


def _rule_spans(text: str, rule: Rule, glob: Allowlist) -> Iterable[tuple[int, int]]:
    for m in rule.regex.finditer(text):
        start, end = _secret_span(m, rule.secret_group)
        if start < 0 or end <= start:
            continue
        secret = text[start:end]
        if rule.entropy and shannon_entropy(secret) <= rule.entropy:
            continue
        line = _line_of(text, m.start(), m.end())
        allowlists = (glob, *rule.allowlists)
        if any(a.allows(secret, m.group(0), line) for a in allowlists):
            continue
        yield start, end


def _drop_shadowed_generic(
    text: str, found: list[tuple[int, int, str]]
) -> list[tuple[int, int, str]]:
    """gitleaks ``filter``: a ``generic`` finding yields to a specific rule's
    finding on the same line whose secret contains it."""

    def line_no(pos: int) -> int:
        return text.count("\n", 0, pos)

    kept = []
    for start, end, rule_id in found:
        secret = text[start:end]
        shadowed = "generic" in rule_id.lower() and any(
            "generic" not in other.lower()
            and other != rule_id
            and line_no(o_start) == line_no(start)
            and secret in text[o_start:o_end]
            for o_start, o_end, other in found
        )
        if not shadowed:
            kept.append((start, end, rule_id))
    return kept


def redaction_spans(text: str, rule_set: RuleSet) -> list[tuple[int, int, str]]:
    """Return ``(start, end, rule_id)`` for every secret gitleaks would report.

    Positions and public rule ids to redact, never the secret text itself."""
    lowered = text.lower()
    found: list[tuple[int, int, str]] = []
    for rule in rule_set.rules:
        if rule.keywords and not any(k in lowered for k in rule.keywords):
            continue
        for start, end in _rule_spans(text, rule, rule_set.global_allowlist):
            found.append((start, end, rule.rule_id))
    return _drop_shadowed_generic(text, found)


def _merge(spans: Sequence[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    merged: list[tuple[int, int, str]] = []
    for start, end, rule_id in sorted(spans):
        if merged and start <= merged[-1][1]:
            prev = merged[-1]
            merged[-1] = (prev[0], max(prev[1], end), prev[2])
        else:
            merged.append((start, end, rule_id))
    return merged


def redact_spans(text: str, spans: Sequence[tuple[int, int, str]]) -> str:
    """Replace each ``(start, end, rule_id)`` span with ``[REDACTED:<rule-id>]``."""
    merged = _merge(spans)
    if not merged:
        return text
    parts: list[str] = []
    cursor = 0
    for start, end, rule_id in merged:
        parts.append(text[cursor:start])
        parts.append(f"{REDACTION_PREFIX}{rule_id}]")
        cursor = end
    parts.append(text[cursor:])
    return "".join(parts)


def redact(text: str, rule_set: RuleSet) -> str:
    """Replace every detected secret with ``[REDACTED:<rule-id>]``."""
    if not text:
        return text
    return redact_spans(text, redaction_spans(text, rule_set))
