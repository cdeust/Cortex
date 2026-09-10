# ADR-0489: mcp_server/hooks/capture_worker_policy.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/hooks/capture_worker_policy.py`; original SHA-256 `5b49dfa8f03c7ae2779b6f8d8f1508784f45cf01638955a1398ab999d8449912`.

## Original comment, lines 12–12

````text
# source: validation/schemas.py remember contract: directory=500, tags=20*80.
````

## Original comment, lines 14–14

````text
# source: validation/schemas.py remember.tags.maxItems.
````

## Original comment, lines 16–16

````text
# source: validation/schemas.py remember.tags.items.maxLength.
````

## Original comment, lines 18–18

````text
# source: mcp_client.py MCPClient.__init__, idleTimeoutMs default 300000 ms.
````

## Original comment, lines 20–20

````text
# source: remediation plan F1/W3-1, existing PostToolUse hook timeout 10 seconds.
````

## Original comment, lines 22–22

````text
# source: RFC 8259 §7: a one-byte control becomes six ASCII bytes (\uXXXX).
````

## Original comment, lines 36–36

````text
# source: post_tool_capture tool-kind sets; executable reconciliation test.
````

## Original comment, lines 43–44

````text
# The fixed metadata has its exact JSON cost; variable strings take their
    # worst escaped size. This includes tag quotes/commas, keys and braces.
````

