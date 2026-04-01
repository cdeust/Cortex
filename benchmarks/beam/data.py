"""BEAM data loading and conversation parsing."""

from __future__ import annotations

import ast
import json
import sys


ABILITIES = [
    "abstention",
    "contradiction_resolution",
    "event_ordering",
    "information_extraction",
    "instruction_following",
    "knowledge_update",
    "multi_hop_reasoning",
    "preference_following",
    "summarization",
    "temporal_reasoning",
]


def load_beam_dataset(split: str = "100K"):
    """Load BEAM dataset from HuggingFace."""
    try:
        from datasets import load_dataset

        return load_dataset("Mohammadta/BEAM", split=split)
    except Exception as e:
        print(f"Error loading dataset: {e}")
        print("Install: pip install datasets")
        sys.exit(1)


def parse_probing_questions(raw: str | dict) -> dict:
    """Parse probing_questions field (may be string or dict)."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            return ast.literal_eval(raw)
        except (ValueError, SyntaxError):
            try:
                return json.loads(raw)
            except (ValueError, TypeError):
                return {}
    return {}


def extract_conversation_turns(chat_data) -> list[dict]:
    """Extract user-assistant turn pairs from BEAM chat format."""
    turns = []
    if isinstance(chat_data, str):
        try:
            chat_data = json.loads(chat_data)
        except (ValueError, TypeError):
            try:
                chat_data = ast.literal_eval(chat_data)
            except (ValueError, SyntaxError):
                return turns

    if isinstance(chat_data, dict):
        raw_turns = chat_data.get("turns", [])
    elif isinstance(chat_data, list):
        raw_turns = chat_data
    else:
        return turns

    for turn_group in raw_turns:
        if isinstance(turn_group, list):
            for msg in turn_group:
                if isinstance(msg, dict):
                    turns.append(
                        {
                            "role": msg.get("role", "user"),
                            "content": msg.get("content", ""),
                            "time_anchor": msg.get("time_anchor", ""),
                            "id": msg.get("id", 0),
                        }
                    )
        elif isinstance(turn_group, dict):
            turns.append(
                {
                    "role": turn_group.get("role", "user"),
                    "content": turn_group.get("content", ""),
                    "time_anchor": turn_group.get("time_anchor", ""),
                    "id": turn_group.get("id", 0),
                }
            )

    return turns


def turns_to_memories(turns: list[dict]) -> list[dict]:
    """Convert conversation turns to memory units (user-assistant pairs).

    BEAM conversations have 3 time_anchors marking session boundaries.
    Propagate each time_anchor forward to subsequent turns in the same
    session — if a session starts on March-15-2024, all turns in that
    session are from March-15-2024.  This gives the temporal/recency
    retrieval signals meaningful values instead of defaulting to NOW().
    """
    memories = []
    # Track the most recent time_anchor seen — propagate forward
    last_anchor = ""
    i = 0
    while i < len(turns):
        user_content = ""
        assistant_content = ""

        if turns[i]["role"] == "user":
            user_content = turns[i]["content"]
            turn_anchor = turns[i].get("time_anchor", "")
            if turn_anchor:
                last_anchor = turn_anchor
            if i + 1 < len(turns) and turns[i + 1]["role"] == "assistant":
                assistant_content = turns[i + 1]["content"]
                # Check assistant turn for anchor too
                asst_anchor = turns[i + 1].get("time_anchor", "")
                if asst_anchor:
                    last_anchor = asst_anchor
                i += 2
            else:
                i += 1
        else:
            assistant_content = turns[i]["content"]
            turn_anchor = turns[i].get("time_anchor", "")
            if turn_anchor:
                last_anchor = turn_anchor
            i += 1

        # Only include [Date:] in content if this turn pair originally had
        # a time_anchor — avoids diluting embeddings with repeated dates.
        # The propagated `last_anchor` still feeds `created_at` for recency.
        display_anchor = ""
        pair_start = max(0, i - 2 if user_content and assistant_content else i - 1)
        for ti in range(pair_start, min(pair_start + 2, len(turns))):
            if turns[ti].get("time_anchor", ""):
                display_anchor = turns[ti]["time_anchor"]
                break

        content = ""
        if display_anchor:
            content += f"[Date: {display_anchor}] "
        if user_content:
            content += f"[user]: {user_content}"
        if assistant_content:
            content += f"\n[assistant]: {assistant_content}"

        if content.strip():
            memories.append(
                {
                    "content": content.strip(),
                    "created_at": last_anchor if last_anchor else "",
                    "user_content": user_content,
                }
            )

    return memories
