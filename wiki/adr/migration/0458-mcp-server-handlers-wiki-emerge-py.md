# ADR-0458: mcp_server/handlers/wiki_emerge.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/handlers/wiki_emerge.py`; original SHA-256 `1a43c2b593a36b88d7b1500070d105b0489bedf87297a5ba0db6934f276378b6`.

## Original comment, lines 224–227

````text
# Cold-start detection: measured against TOTAL resolved-claim
    # corpus size, not the loaded batch. That way a large corpus
    # processed in small pages still runs with steady-state rules,
    # and fresh installs benefit from the relaxed thresholds.
````

## Original comment, lines 238–242

````text
# A `SELECT COUNT(*)` with no GROUP BY always returns exactly one row,
        # so `row is None` is unreachable here; the guard makes that explicit
        # for the type checker (fetchone is typed Optional) and degrades to the
        # cold-start path (0 claims) rather than raising if the invariant ever
        # breaks. No observable behavior change on the reachable path.
````

