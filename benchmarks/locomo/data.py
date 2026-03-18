"""LoCoMo data loading and session extraction."""

from __future__ import annotations

import json
import re


CATEGORY_NAMES = {
    1: "single_hop",
    2: "multi_hop",
    3: "temporal",
    4: "open_domain",
    5: "adversarial",
}


def load_locomo(data_path: str) -> list[dict]:
    with open(data_path) as f:
        return json.load(f)


def parse_evidence_refs(evidence: list[str]) -> list[tuple[int, int]]:
    """Parse evidence references like 'D1:3' into (session_idx, turn_idx)."""
    refs = []
    for ref in evidence:
        m = re.match(r"D(\d+):(\d+)", ref)
        if m:
            refs.append((int(m.group(1)), int(m.group(2))))
    return refs


def extract_sessions(conversation: dict) -> list[dict]:
    """Extract all sessions with their turns and metadata."""
    sessions = []
    for i in range(1, 100):
        key = f"session_{i}"
        date_key = f"session_{i}_date_time"
        if key not in conversation:
            break
        turns = conversation[key]
        if not turns:
            continue
        date = conversation.get(date_key, "")
        parts = []
        if date:
            parts.append(f"[Date: {date}]")
        for turn in turns:
            speaker = turn.get("speaker", "User")
            text = turn.get("text", "")
            parts.append(f"[{speaker}]: {text}")

        sessions.append(
            {
                "session_idx": i,
                "date": date,
                "content": "\n".join(parts),
                "turns": turns,
                "user_content": "\n".join(
                    turn["text"]
                    for turn in turns
                    if turn.get("speaker", "") == conversation.get("speaker_a", "")
                ),
            }
        )
    return sessions
