# ADR-0441: mcp_server/handlers/remember_response.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/handlers/remember_response.py`; original SHA-256 `5eec7656273728f50fcad3c335432dde5c160129aca5ccd432342b473de9ebb3`.

## Original comment, lines 69–71

````text
# Normalize internal curation action vocab → schema-canonical enum.
    # try_curation returns "create"/"link" (present-tense ops); the public
    # schema documents past-tense outcomes (stored / merged / rejected).
````

