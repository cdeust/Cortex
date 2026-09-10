# ADR-0490: mcp_server/hooks/compaction_checkpoint.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/hooks/compaction_checkpoint.py`; original SHA-256 `d6bebdb5eb8f9d3328c61684f4e806970afee977fbe493a8d4c99c8a5183a055`.

## Original comment, lines 66–71

````text
# Q2 alignment (decision 4255039 correction 7): Notification events
        # carry the same {"session_id", "transcript_path", ...} envelope as
        # every other Claude Code hook (session_start.py:49). Prefer the
        # transcript-stem identity when available; the raw event session_id
        # (defaulting to "auto-compaction" for synthetic/test events with no
        # transcript_path) is the documented degradation, not a regression.
````

## Original comment, lines 131–135

````text
# issue #398: closes the store before this one-shot process exits
    # (see _store_lifecycle.py for the verified mechanism -- psycopg pool
    # threads are daemon threads; the fragile path is __del__'s
    # finalization-time join, which close() pre-empts by setting
    # _closed=True while the interpreter is still alive).
````

