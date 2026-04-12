# Provenance

View, add, or verify provenance records for source-tracked files.

## Instructions

1. Parse $ARGUMENTS for the subcommand:
   - `provenance show <file>` — display the provenance sidecar for a file
   - `provenance add <file> <url> <status>` — add a source record (status: consulted, accepted, rejected, stale)
   - `provenance verify <file>` — check all URLs in provenance are reachable
   - `provenance list` — show all provenance files in the repo
   - `provenance init <file>` — create a new provenance sidecar

2. **Show**: Run `tools/provenance-manager.sh show <file>`. Display the provenance table. If no provenance file exists, suggest running `provenance init <file>` first.

3. **Add**: Validate that `<url>` looks like a URL (starts with http:// or https://). Validate `<status>` is one of: consulted, accepted, rejected, stale. Run `tools/provenance-manager.sh add <file> <url> <status>`. Confirm what was added.

4. **Verify**: Run `tools/provenance-manager.sh verify <file>`. Report results clearly:
   - All reachable: confirm clean provenance
   - Any stale: list the stale URLs and suggest updating or replacing them

5. **List**: Run `tools/provenance-manager.sh list`. Format as a readable summary showing file count and total sources.

6. **Init**: Run `tools/provenance-manager.sh init <file>`. Confirm creation and remind user to add sources with `provenance add`.

7. If no subcommand given, run `provenance list` as default.

8. The zetetic standard requires multiple independent sources. If a file has fewer than 2 accepted sources, note this as a gap.

$ARGUMENTS
