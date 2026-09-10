# ADR-0391: mcp_server/handlers/explore_features.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/handlers/explore_features.py`; original SHA-256 `afb22e4f1a223e3355e8e9472020cd2b3ce84f5a74c235da3cbabfc31e846744`.

## Original comment, lines 24–31

````text
# Bound on how many real sessions the attribution mode fetches from disk.
# source: measured 2026-07-10 on this environment -- a discover_conversations_
# for_projects() scan capped at 20 sessions from one project directory takes
# ~12ms (vs ~270ms for an unscoped full-history scan), keeping the handler
# within the tool schema's documented "Latency <100ms" budget. Matches the
# pre-existing MAX_SAMPLES truncation already applied downstream in
# attribution_tracer.py (conversations[:20]), so fetching more here would
# only be discarded by trace_attribution before use.
````

## Original docstring, lines 279–284

````text
"""Validate the disk-persisted persistentFeatures, or compute them fresh.

    Same boundary-validation pattern as _resolve_feature_dictionary: the
    disk-loaded list is untyped JSON; validate once here so the caller
    always holds list[PersistentFeature].
    """
````

