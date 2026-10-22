#!/usr/bin/env bash
# Usage: run_probe.sh <label> <cmd...>  — runs cmd with a fresh HOME, no DB env, listener on :5432; prints connects.
set -u
label=$1; shift
P=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd); R=$(cd "$P/../.." && pwd); H=$(mktemp -d "$P/home.XXXX"); L="$P/$label.connects.log"; : > "$L"
python3 "$P/pg_listener.py" "$L" & LP=$!; sleep 0.5
env -i PATH="$PATH" HOME="$H" LANG=C.UTF-8 CLAUDE_PLUGIN_ROOT="$R" PLUGIN_ROOT="$R/plugins/hypermnesia-mcp-codex" \
   CLAUDE_PLUGIN_DATA="${PROBE_PLUGIN_DATA:-$H/plugindata}" HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
   timeout 120 "$@" < /dev/null > "$P/$label.out" 2> "$P/$label.err"; rc=$?
sleep 1; kill $LP 2>/dev/null; wait $LP 2>/dev/null
echo "[$label] exit=$rc connects_to_5432=$(wc -l < "$L") marker=$(cat "$H/.claude/methodology/backend.json" 2>/dev/null | tr -d '\n ' || echo none)"
tail -3 "$P/$label.err" | sed "s/^/   err: /"
