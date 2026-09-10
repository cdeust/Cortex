# ADR-0393: mcp_server/handlers/get_causal_chain.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/handlers/get_causal_chain.py`; original SHA-256 `9586778efe01dc21d4fa851e9e4961706722a882aeeb93f715d9d19c6aead3cc`.

## Original docstring, lines 1–8

````text
"""Handler: get_causal_chain — trace entity relationships through the knowledge graph.

Given an entity name (or memory ID), performs BFS through the relationship
graph to surface chains of causation, dependency, and resolution.

Useful for: understanding why a bug occurred, tracing a decision's origin,
following an import chain across modules.
"""
````

## Original docstring, lines 239–243

````text
"""Fetch and format memory previews mentioning an entity.

    heads_only: previews are served content — with heat-DESC ordering a
    superseded version could rank ahead of its correction.
    """
````

## Original comment, lines 301–302

````text
# Telemetry-instrumented public entry. Records latency / byte volume
# / result count per call (Popper C6 read/write ratio audit).
````

