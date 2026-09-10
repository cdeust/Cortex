# ADR-0488: mcp_server/hooks/capture_worker_logging.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/hooks/capture_worker_logging.py`; original SHA-256 `609591938c7616f4906c04e8a4909e40c2e37b651c1514d8b02dd18b4bc5306a`.

## Original comment, lines 11–11

````text
# source: remediation F9, measured 2026-09-06: 196 kB/day; 30 days ≈ 6 MB.
````

## Original comment, lines 29–29

````text
# Retain the immediately previous segment; no accumulated unbounded history.
````

