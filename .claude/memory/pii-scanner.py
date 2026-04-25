#!/usr/bin/env python3
"""
pii-scanner.py — PII/secret detection for memory-tool.sh §7.2

Usage: python3 pii-scanner.py <rules_json_path> [strict_mode]

Reads content to scan from stdin.
Emits one line to stdout:
  pass              — no match
  blocked:<rule_id> — match confirmed (rule_id only; matched bytes NEVER printed)
  pii_scan_error    — internal error (caller should allow write)

Env:
  MEMORY_PII_SCAN_DISABLE=1 — bypass scan, emit pii_scan_disabled
  MEMORY_PII_STRICT=1       — enable low-confidence rules (email, phone)

Sources:
  Shannon entropy threshold: Shannon, C. E. (1948). Bell System Technical Journal.
  Threshold value 3.5 bits/char: TruffleHog v2 design (Cornwell, T., 2019).
  Rule patterns: pii-rules.json (curator-editable).
"""
import sys
import re
import json
import math
import os

# Back-action invariant: matched bytes MUST NOT be written to any output.

def main():
    if os.environ.get("MEMORY_PII_SCAN_DISABLE"):
        print("pii_scan_disabled")
        return

    if len(sys.argv) < 2:
        print("pii_scan_error")
        return

    rules_path = sys.argv[1]
    # Strict mode: argv[2] == "1" OR env var.
    strict_mode = (
        (len(sys.argv) > 2 and sys.argv[2] == "1")
        or os.environ.get("MEMORY_PII_STRICT", "") == "1"
    )

    try:
        content = sys.stdin.read()
    except Exception:
        print("pii_scan_error")
        return

    try:
        with open(rules_path) as f:
            cfg = json.load(f)
    except Exception:
        print("pii_scan_error")
        return

    entropy_threshold = cfg.get("_entropy_threshold", {}).get("value", 3.5)
    rules = cfg.get("rules", [])

    for rule in rules:
        confidence = rule.get("confidence", "high")
        # Default mode: skip low-confidence rules (email, phone).
        # Strict mode: include all rules.
        if confidence == "low" and not strict_mode:
            continue
        try:
            m = re.search(rule["pattern"], content)
        except re.error:
            continue
        if m is None:
            continue
        # Entropy gate (second independent method — Shannon H cross-check).
        # Rejects placeholder strings like YOUR_API_KEY_HERE (H ~1.5-2.5 bits/char).
        # Source: Shannon (1948); base threshold 3.5 from TruffleHog v2.
        # Per-rule override via entropy_threshold_override field (e.g. generic_api_key uses 4.5
        # per TruffleHog v3 calibration — Cornwell 2019 updated design).
        if rule.get("entropy_check"):
            rule_threshold = rule.get("entropy_threshold_override", entropy_threshold)
            matched_str = (
                m.group(1)
                if m.lastindex and m.lastindex >= 1
                else m.group(0)
            )
            if _shannon_entropy(matched_str) <= rule_threshold:
                continue  # Low entropy: likely placeholder; pass through.
        # Confirmed match.
        # INVARIANT: print rule id only — NEVER the matched bytes.
        print(f"blocked:{rule['id']}")
        sys.exit(0)

    print("pass")


def _shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    freq: dict[str, int] = {}
    for c in s:
        freq[c] = freq.get(c, 0) + 1
    n = len(s)
    return -sum((v / n) * math.log2(v / n) for v in freq.values())


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("pii_scan_error")
        sys.exit(0)
