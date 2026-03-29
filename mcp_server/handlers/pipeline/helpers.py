"""Shared helpers for pipeline stages."""

from __future__ import annotations

import json
import re
import sys
from typing import Any

from mcp_server.core.context_generator import generate_context
from mcp_server.core.domain_detector import detect_domain
from mcp_server.infrastructure.profile_store import load_profiles


def log(msg: str) -> None:
    print(f"[run-pipeline] {msg}", file=sys.stderr)


def trunc(s: str | None, n: int) -> str:
    return (s or "")[:n]


def extract_text(result: Any) -> str:
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        return (
            result.get("enhanced")
            or result.get("original")
            or result.get("content")
            or ""
        )
    return ""


def try_parse_json(s: Any) -> Any:
    if not isinstance(s, str):
        return s
    stripped = re.sub(r"^```(?:json)?\n?", "", s, flags=re.MULTILINE)
    stripped = re.sub(r"\n?```$", "", stripped, flags=re.MULTILINE).strip()
    try:
        return json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return None


def finding_to_prd_type(finding: dict) -> str:
    cat = (
        finding.get("relevance_category_label") or finding.get("domain") or ""
    ).lower()
    if any(k in cat for k in ("bug", "fix", "defect")):
        return "bug"
    if any(k in cat for k in ("propos", "rfc", "idea")):
        return "proposal"
    return "feature"


def get_cognitive_context(cwd: str) -> str:
    try:
        profiles = load_profiles()
        detection = detect_domain({"cwd": cwd}, profiles)
        if detection.get("coldStart") or not detection.get("domain"):
            return ""
        profile = profiles.get("domains", {}).get(detection["domain"])
        if not profile:
            return ""
        return generate_context(detection["domain"], profile)
    except Exception:
        return ""
