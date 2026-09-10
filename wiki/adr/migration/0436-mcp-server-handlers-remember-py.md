# ADR-0436: mcp_server/handlers/remember.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/handlers/remember.py`; original SHA-256 `57fad20238b56cd41a4fe3486c6339837b2c280aa10928f09f6eb4dd2300514e`.

## Original docstring, lines 100–110

````text
"""Extract and default handler arguments.

    Second-to-last element `initial_heat` is the optional age-adjusted
    baseline used by backfill / import paths (issue #14 P1). None = legacy
    1.0 baseline. Defensive clamp to [0, 1] — schema validation enforces
    the same bounds.

    Last element `write_class` is the raw, UNVALIDATED explicit class
    argument (M-D2, 7.4) — None when the caller omitted it. Validation
    happens in `_handler_impl` (the write-time contract), not here.
    """
````

## Original comment, lines 299–304

````text
# Explicit supersession: the caller's intent overrides automatic
        # curation (no merge/link second-guessing) and the block-replica
        # upsert. force=True composes with it — the gate was bypassed
        # above, yet the edge is still posted below (sovereign human
        # correction; previously force and supersede were exclusive
        # because force early-returned "create" inside try_curation).
````

## Original comment, lines 307–312

````text
# Block-replica upsert: if the incoming memory is a system-memory block
        # snapshot (tagged 'memory-replica' + 'vpath:…'), refresh the existing row
        # in-place rather than inserting a new one (one row per block file).
        # Normal writes are completely unaffected — this branch exits early on
        # any write that isn't a replica.
        # contract: zetetic-team-subagents memory/contract.md §8b
````

## Original comment, lines 367–377

````text
# Promote decision-shaped memories to the authored wiki layer.
    #
    # Contract (E8, post-Taleb fragility audit):
    #   - On success: ``result["wiki_page"]`` is the relative path.
    #   - On classifier rejection: no field added (memory didn't qualify).
    #   - On wiki I/O failure: memory write is already committed; we log
    #     the failure to ``result["warnings"]`` so the caller can observe
    #     the partial failure rather than silently losing the signal.
    #
    # The store write has succeeded by this point; a failure here is a
    # partial-failure, not a total one. Documented in the schema.
````

## Original comment, lines 406–407

````text
# Telemetry-instrumented public entry. Records latency, byte volume,
# and write success/fail per call (Popper C6 read/write ratio audit).
````

## Reviewed remaining docstring (mcp_server/handlers/remember.py, interim lines 151–155)

````text
Issue #365: trust the producing channel, never attacker-controlled content.

Only an absent tool name on a deliberate write is promoted to deliberate.
Named but unknown tools keep UNKNOWN; auto captures cannot claim this bypass.
````

