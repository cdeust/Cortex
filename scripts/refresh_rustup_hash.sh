#!/usr/bin/env bash
# Refresh scripts/rustup-init.sha256 with the current SHA256 of the
# rustup bootstrap installer at https://sh.rustup.rs.
#
# Run AFTER manually auditing the upstream script. The hash is the
# trust anchor for every fresh Cortex install — never refresh
# blindly. Diff the bootstrap against the previous known-good copy
# before committing the new digest.
#
# Usage:  bash scripts/refresh_rustup_hash.sh

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
