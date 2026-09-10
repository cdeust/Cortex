#!/usr/bin/env bash
# source: ADR-0778

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MANIFEST="${SCRIPT_DIR}/rustup-init.sha256"

DIGEST="$(curl -sSf https://sh.rustup.rs | shasum -a 256 | awk '{print $1}')"

if [ -z "$DIGEST" ] || [ "${#DIGEST}" -ne 64 ]; then
    echo "ERROR: failed to compute a 64-char SHA256" >&2
    exit 1
fi

# Strip any existing non-comment lines, append the new digest.
TMP="$(mktemp)"
grep -E '^\s*(#|$)' "$MANIFEST" > "$TMP" || true
printf '%s\n' "$DIGEST" >> "$TMP"
mv "$TMP" "$MANIFEST"

echo "[ok] rustup-init.sha256 refreshed: $DIGEST"
