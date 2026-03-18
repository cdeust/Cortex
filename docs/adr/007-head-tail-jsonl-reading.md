# ADR-007: Head+Tail JSONL Reading Strategy

## Status
Accepted

## Context
Conversation JSONL files can exceed 10MB for long sessions. Reading entire files is slow and unnecessary — most analytical value is in the session start (first messages, tool choices) and session end (final state, outcomes).

## Decision
Read only the first 32KB (head) and last 8KB (tail) of each JSONL file. Parse available complete JSON lines from each chunk.

## Consequences
- **Gain**: ~40KB read per file regardless of actual size. Predictable performance. Captures session metadata, initial prompts, entry points (head) and final tool usage, outcomes (tail).
- **Lose**: Middle content is invisible. Long multi-phase sessions lose intermediate transitions. Some sessions may have important mid-session domain shifts that are missed.
- **Neutral**: For cognitive profiling, the beginning and end of a session are the most informative signals. The 32KB head typically captures 5-15 messages, sufficient for entry point and style detection.

## References
- Performance optimization pattern: bounded I/O for unbounded inputs
- Similar approach used in log analysis tools (reading head/tail of large log files)
