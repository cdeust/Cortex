# ADR-0439: mcp_server/handlers/remember_preflight.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/handlers/remember_preflight.py`; original SHA-256 `a8c1e179f55a47ae48a91ea72e1129267f3867605189c00170bc18d99faac2a3`.

## Original docstring, lines 69–75

````text
"""Reject only when the maximum attainable novelty is strictly too low.

    source: predictive_coding_flat.compute_novelty_score uses positive weights;
    embedding and temporal outputs are bounded by one. Temporal depends on
    the vector-selected nearest memory and cannot be observed before encode.
    Both subsequent multiply/clamp modulations are monotone in novelty.
    """
````

