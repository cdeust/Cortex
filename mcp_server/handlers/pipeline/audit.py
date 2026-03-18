"""Stage 8: YAML Audit — rule-based PRD quality checks."""

from __future__ import annotations

import re
from pathlib import Path

from mcp_server.handlers.pipeline.helpers import log


def parse_yaml_rules_naive(yaml_text: str) -> list[dict]:
    """Parse YAML rule definitions into structured dicts."""
    rules: list[dict] = []
    current: dict | None = None
    for line in yaml_text.split("\n"):
        trimmed = line.strip()
        if trimmed.startswith("- id:"):
            if current:
                rules.append(current)
            current = {
                "id": trimmed[5:].strip(),
                "patterns": [],
                "suppress": [],
                "mode": "presence",
            }
        elif current:
            if trimmed.startswith("mode:"):
                current["mode"] = trimmed[5:].strip().strip("'\"")
            elif trimmed.startswith("- pattern:"):
                current["patterns"].append(trimmed[10:].strip().strip("'\""))
            elif trimmed.startswith("- suppress:"):
                current["suppress"].append(trimmed[11:].strip().strip("'\""))
            elif trimmed.startswith("pattern:"):
                current["patterns"].append(trimmed[8:].strip().strip("'\""))
    if current:
        rules.append(current)
    return rules


def _matches_pattern(pattern: str, content: str) -> bool:
    """Check if a pattern matches content (regex or fallback substring)."""
    try:
        return bool(re.search(pattern, content, re.IGNORECASE))
    except re.error:
        return pattern.lower() in content.lower()


def apply_yaml_rules(rules: list[dict], content: str) -> list[str]:
    """Apply rules to content and return list of flagged rule IDs."""
    flags: list[str] = []
    for rule in rules:
        matched = any(_matches_pattern(pat, content) for pat in rule["patterns"])
        if matched and rule["suppress"]:
            if any(_matches_pattern(sp, content) for sp in rule["suppress"]):
                matched = False
        if rule["mode"] == "presence" and matched:
            flags.append(rule["id"])
        if rule["mode"] == "absence" and not matched:
            flags.append(rule["id"])
    return flags


def _audit_rules_dir(
    rules_dir: Path,
    prd_content: str,
) -> tuple[list[dict], int, int]:
    """Run all rule families against PRD content. Returns (results, rules, flags)."""
    audit_results: list[dict] = []
    total_rules = 0
    total_flags = 0

    for rule_file in sorted(rules_dir.iterdir()):
        if rule_file.suffix not in (".yaml", ".yml"):
            continue
        family = rule_file.stem
        yaml_text = rule_file.read_text(encoding="utf-8")
        rules = parse_yaml_rules_naive(yaml_text)
        flags = apply_yaml_rules(rules, prd_content)
        total_rules += len(rules)
        total_flags += len(flags)
        audit_results.append(
            {
                "family": family,
                "rulesChecked": len(rules),
                "flagsRaised": len(flags),
                "details": flags,
            }
        )
    return audit_results, total_rules, total_flags


async def stage_audit(client, ctx: dict) -> None:
    """Execute the YAML audit stage."""
    log("Stage 8: YAML Audit")

    rules_dir = (
        Path(ctx["codebasePath"])
        / "packages"
        / "AIPRDAuditFlagEngine"
        / "Sources"
        / "Resources"
        / "Rules"
    )
    all_prd_content = "\n\n".join(
        p.get("content", "") for p in ctx["prdFiles"].values()
    )

    if rules_dir.exists():
        audit_results, total_rules, total_flags = _audit_rules_dir(
            rules_dir, all_prd_content
        )
    else:
        log("  rules dir not found, skipping YAML audit")
        audit_results, total_rules, total_flags = [], 0, 0

    ctx.update(
        {
            "auditResults": audit_results,
            "totalRulesChecked": total_rules,
            "totalFlagsRaised": total_flags,
        }
    )
    ctx["stages"][8] = {"status": "ok", "rules": total_rules, "flags": total_flags}
    log(f"  {total_rules} rules, {total_flags} flags")
