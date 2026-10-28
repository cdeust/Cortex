"""Output contract for recall, including JSON and tabular results."""

OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["memories"],
    "properties": {
        "memories": {
            "type": "array",
            "description": (
                # source: ADR-0430
                "Ranked list of matching memories. Best result is index 0. With "
                '``format: "json"`` (default) each element is a memory object; '
                'with ``format: "tabular"`` each element is a cell array whose '
                "fields are named once in the sibling ``columns`` header."
            ),
            "items": {
                "oneOf": [
                    {
                        "type": "object",
                        "properties": {
                            "id": {
                                "type": "string",
                                "description": (
                                    "Memory UUID or wiki:ADR-NNNN identity."
                                ),
                            },
                            "content": {
                                "type": "string",
                                "description": "Memory body.",
                            },
                            "score": {
                                "type": "number",
                                "description": "Final fused + reranked score.",
                            },
                            "heat": {
                                "type": "number",
                                "description": "Current thermodynamic heat [0,1].",
                            },
                            "domain": {"type": "string"},
                            "tags": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "created_at": {
                                "type": "string",
                                "format": "date-time",
                            },
                            "source": {"type": "string"},
                            "capture_origin": {
                                "type": "string",
                                "description": (
                                    "Capture channel: deliberate, local_action, "
                                    "network, unknown or legacy."
                                ),
                            },
                            "truncated": {
                                "type": "boolean",
                                "description": (
                                    "Present and true when content was cut "
                                    "to fit the response budget. Fetch the "
                                    "full body via the memory_id argument."
                                ),
                            },
                            "content_length": {
                                "type": "integer",
                                "description": (
                                    "Original content size in chars (set "
                                    "when truncated)."
                                ),
                            },
                        },
                    },
                    {
                        "type": "array",
                        "description": (
                            "Tabular row (format=tabular): cells in the "
                            "order named by the ``columns`` header."
                        ),
                    },
                ],
            },
        },
        "columns": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                # source: ADR-0430
                "Present only when ``format`` is ``tabular``: the field names, in "
                "order, that each row array in ``memories`` carries. Declared "
                "once so field names are not repeated per memory."
            ),
        },
        "format": {
            "type": "string",
            "enum": ["json", "tabular"],
            "description": (
                "The encoding applied to ``memories``: ``json`` (array of "
                "objects, default) or ``tabular`` (array of cell arrays + "
                "a ``columns`` header). Self-describes the response so a "
                "client reads rows correctly without guessing."
            ),
        },
        "intent": {
            "type": "string",
            # source: ADR-0430
            "enum": [
                "temporal",
                "causal",
                "semantic",
                "entity",
                "knowledge_update",
                "multi_hop",
                "instruction",
                "event_order",
                "summarization",
                "preference",
                "general",
            ],
            "description": (
                "Classified query intent that drove the signal-weight profile."
            ),
        },
        "count": {"type": "integer", "description": "Number of memories returned."},
        "low_signal_dropped": {
            "type": "integer",
            "description": ("System captures hidden from the retrieved candidate set."),
        },
        "receipt_id": {
            "type": "integer",
            "description": (
                "Append-only injection receipt recording exactly the "
                "memories in this response. Absent when no memory "
                "was injected or the "
                "receipt write failed."
            ),
        },
    },
}
