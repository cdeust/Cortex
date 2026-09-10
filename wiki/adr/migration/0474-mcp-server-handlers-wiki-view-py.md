# ADR-0474: mcp_server/handlers/wiki_view.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `mcp_server/handlers/wiki_view.py`; original SHA-256 `7698201181de40c319d4b6f27c726e4fe6a73f71275eb9286a17df2afee52228`.

## Original comment, lines 220–221

````text
# Guard: wiki_view DB execution is PG-only. Under SQLite return a
    # structured explanation instead of ImportError / AttributeError.
````

