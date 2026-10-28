"""Translate the vendored gitleaks rule set into the JSON the redaction gate loads.

Input: ``third_party/gitleaks/<version>/gitleaks.toml``, byte-identical to the
upstream file at the pinned tag (its SHA-256 is checked against
``PROVENANCE.json`` before anything is read). Output:
``mcp_server/shared/redaction_rules/gitleaks.json``.

Gitleaks regexes are Go RE2. Python ``re`` differs in three ways that occur in
the pinned file, each translated mechanically here:

1. an inline ``(?i)`` that is not at the start of the pattern (Python 3.11+
   rejects it; RE2 applies it to the rest of the enclosing group) becomes a
   scoped ``(?i:...)`` group closed where the enclosing group closes;
2. ``\\z`` (RE2 end of text) becomes ``\\Z`` (Python end of string);
3. POSIX classes inside a bracket (``[[:alnum:]]``) are expanded.

An alternation that follows a mid-pattern flag keeps the flag (RE2 scopes it
to the whole rest of the group), so the scoped group is closed before the bar
and reopened after it. A rule whose pattern still fails to compile is listed
in ``skipped`` with its reason; nothing is dropped silently. Path-only rules
(no ``regex``) and path-scoped rules (a ``regex`` gitleaks applies only to
files whose name matches ``path``) cannot apply to text without a file name
and are skipped too.

Usage: ``python scripts/vendor_gitleaks_rules.py [--check]`` (``--check``
exits 1 when the committed JSON differs from a fresh translation).

source: ADR-1110"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
VENDOR_DIR = (
    REPO_ROOT / "third_party" / "gitleaks" / "v8.30.1"
)  # source: ADR-1110 (pinned tag)
OUTPUT = REPO_ROOT / "mcp_server" / "shared" / "redaction_rules" / "gitleaks.json"

_POSIX_CLASSES = {
    "alnum": "a-zA-Z0-9",
    "alpha": "a-zA-Z",
    "digit": "0-9",
    "xdigit": "0-9A-Fa-f",
    "upper": "A-Z",
    "lower": "a-z",
}


class UntranslatableError(ValueError):
    """The RE2 pattern has no faithful Python translation."""


def _expand_posix(pattern: str) -> str:
    def repl(m: re.Match[str]) -> str:
        name = m.group(1)
        if name not in _POSIX_CLASSES:
            raise UntranslatableError(f"POSIX class [:{name}:] not mapped")
        return _POSIX_CLASSES[name]

    return re.sub(r"\[:([a-z]+):\]", repl, pattern)


def _scan_class(pattern: str, i: int) -> int:
    """Return the index just past the bracket expression starting at ``i``."""
    j = i + 1
    if j < len(pattern) and pattern[j] == "^":
        j += 1
    if j < len(pattern) and pattern[j] == "]":
        j += 1
    while j < len(pattern) and pattern[j] != "]":
        j += 2 if pattern[j] == "\\" else 1
    return j + 1


def _scope_inline_flags(pattern: str) -> str:
    """Rewrite each non-leading ``(?i)`` as ``(?i:`` closed with its group."""
    out: list[str] = []
    pending = [0]  # extra ")" to emit when the current group closes
    flagged = [False]  # a mid-pattern flag is open at this depth
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if ch == "\\":
            out.append(pattern[i : i + 2])
            i += 2
        elif ch == "[":
            end = _scan_class(pattern, i)
            out.append(pattern[i:end])
            i = end
        elif pattern.startswith("(?i)", i) and out:
            out.append("(?i:")
            pending[-1] += 1
            flagged[-1] = True
            i += 4
        elif ch == "(":
            out.append(ch)
            pending.append(0)
            flagged.append(False)
            i += 1
        elif ch == ")":
            out.append(")" * pending.pop() + ")")
            flagged.pop()
            i += 1
        elif ch == "|" and flagged[-1]:
            # RE2: the flag holds for the following alternatives of the same
            # group too, so close the scope and reopen it after the bar.
            out.append(")" * pending[-1] + "|" + "(?i:" * pending[-1])
            i += 1
        else:
            out.append(ch)
            i += 1
    out.append(")" * pending[0])
    return "".join(out)


def translate(pattern: str) -> str:
    """Translate one RE2 pattern to Python ``re`` syntax, or raise."""
    translated = _scope_inline_flags(_expand_posix(pattern)).replace(r"\z", r"\Z")
    try:
        re.compile(translated)
    except re.error as exc:
        raise UntranslatableError(f"python re: {exc}") from exc
    return translated


def _allowlist(raw: dict) -> dict:
    return {
        "condition": raw.get("condition", "OR").upper(),
        "regex_target": raw.get("regexTarget", "secret"),
        "regexes": [translate(r) for r in raw.get("regexes", [])],
        "stopwords": sorted({w.lower() for w in raw.get("stopwords", [])}),
        "has_paths": bool(raw.get("paths")),
    }


def _rule(raw: dict) -> dict:
    return {
        "id": raw["id"],
        "regex": translate(raw["regex"]),
        "secret_group": int(raw.get("secretGroup", 0)),
        "entropy": float(raw.get("entropy", 0.0)),
        "keywords": sorted({k.lower() for k in raw.get("keywords", [])}),
        "allowlists": [_allowlist(a) for a in raw.get("allowlists", [])],
    }


def _load_pinned_toml() -> tuple[dict, dict]:
    import tomllib  # noqa: PLC0415 — stdlib from 3.11; this offline script needs it, the runtime never imports it

    provenance = json.loads((VENDOR_DIR / "PROVENANCE.json").read_text())
    raw = (VENDOR_DIR / "gitleaks.toml").read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != provenance["sha256"]:
        raise SystemExit(
            f"gitleaks.toml sha256 {digest} != pinned {provenance['sha256']}"
        )
    return tomllib.loads(raw.decode("utf-8")), provenance


def build() -> dict:
    """Return the translated rule document (deterministic)."""
    cfg, provenance = _load_pinned_toml()
    rules, skipped = [], []
    for raw in cfg["rules"]:
        if "regex" not in raw:
            skipped.append(
                {"id": raw["id"], "reason": "path-only rule: needs a file name"}
            )
            continue
        if "path" in raw:
            reason = f"path-scoped rule (files matching {raw['path']})"
            skipped.append({"id": raw["id"], "reason": f"{reason}: needs a file name"})
            continue
        try:
            rules.append(_rule(raw))
        except UntranslatableError as exc:
            skipped.append({"id": raw["id"], "reason": str(exc)})
    glob = cfg.get("allowlist", {})
    return {
        "source": provenance,
        "global_allowlist": {
            "regexes": [translate(r) for r in glob.get("regexes", [])],
            "stopwords": sorted({w.lower() for w in glob.get("stopwords", [])}),
        },
        "rules": rules,
        "skipped": skipped,
    }


def render(doc: dict) -> str:
    return json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    text = render(build())
    if args.check:
        same = OUTPUT.is_file() and OUTPUT.read_text(encoding="utf-8") == text
        print("up to date" if same else f"{OUTPUT} is stale: rerun without --check")
        return 0 if same else 1
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
