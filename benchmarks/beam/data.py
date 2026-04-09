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
    """Load BEAM dataset from HuggingFace.

    100K/500K/1M live in `Mohammadta/BEAM`.
    10M lives in a separate repo `Mohammadta/BEAM-10M` with the same
    schema except `chat` is a list and each conversation has a `plans`
    array of 10 sub-plans whose chats together form ~10M tokens.
    """
    try:
        from datasets import load_dataset

        if split == "10M":
            return load_dataset("Mohammadta/BEAM-10M", split="10M")
        return load_dataset("Mohammadta/BEAM", split=split)
    except Exception as e:
        print(f"Error loading dataset: {e}")
        print("Install: pip install datasets")
        sys.exit(1)


def extract_10m_chat(conversation: dict) -> list:
    """Aggregate all turns from all 10 plans of a BEAM-10M conversation.

    BEAM-10M turn IDs are **plan-relative** (0..N per plan), but the
    probing questions' ``source_chat_ids`` use a **global** numbering
    that treats the 10 plans as one concatenated sequence.

    This function re-numbers each message's ``id`` field to the global
    scheme so the benchmark scoring loop can match source_chat_ids to
    the flattened turn list. It also tags each message with a
    ``plan_id`` field so `turns_to_memories` can propagate it into
    memory ``agent_context`` for stage-aware retrieval.

    The global offset per plan = cumulative count of messages in all
    preceding plans. Verified against BEAM-10M dataset conv 0 where
    source_chat_ids range [20..15675] and plan sizes sum to 19895.
    """
    plans = conversation.get("plans", [])
    if not plans:
        return conversation.get("chat", [])

    all_batches: list = []
    global_offset = 0

    for plan_idx, plan in enumerate(plans):
        chat = plan.get("chat", [])
        if not isinstance(chat, list):
            continue
        plan_id = f"plan-{plan_idx}"
        plan_msg_count = 0
        remapped_batches: list = []

        for batch in chat:
            if not isinstance(batch, list):
                continue
            remapped_msgs: list = []
            for msg in batch:
                if not isinstance(msg, dict):
                    continue
                # Copy message and re-number id to global
                m = dict(msg)
                orig_id = m.get("id", 0)
                if isinstance(orig_id, int):
                    m["id"] = orig_id + global_offset
                m["plan_id"] = plan_id
                remapped_msgs.append(m)
                plan_msg_count += 1
            remapped_batches.append(remapped_msgs)

        all_batches.extend(remapped_batches)
        global_offset += plan_msg_count

    return all_batches


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
                            "plan_id": msg.get("plan_id", ""),
                        }
                    )
        elif isinstance(turn_group, dict):
            turns.append(
                {
                    "role": turn_group.get("role", "user"),
                    "content": turn_group.get("content", ""),
                    "time_anchor": turn_group.get("time_anchor", ""),
                    "id": turn_group.get("id", 0),
                    "plan_id": turn_group.get("plan_id", ""),
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
            # Stage ID = time_anchor when present, fallback to "stage-0".
            # For 100K/500K/1M splits the BEAM conversations have 3 time
            # anchors marking session boundaries, so each conversation
            # naturally decomposes into 3 stages. For 10M we also set
            # plan_id per (user,assistant) pair from the plan index.
            # Stage ID: for 10M, prefer plan_id (from extract_10m_chat);
            # for 100K/500K/1M, fall back to time_anchor session.
            turn_plan = turns[max(0, i - 1)].get("plan_id", "")
            stage_id = (
                turn_plan if turn_plan else (last_anchor if last_anchor else "stage-0")
            )
            memories.append(
                {
                    "content": content.strip(),
                    "created_at": last_anchor if last_anchor else "",
                    "user_content": user_content,
                    "plan_id": stage_id,
                    # Also propagate into agent_context so the stage
                    # survives ingest (memory_ingest passes agent_context
                    # through to the DB). The assembler reads stages
                    # from this field at benchmark time.
                    "agent_context": f"beam:{stage_id}",
                }
            )

    return memories
