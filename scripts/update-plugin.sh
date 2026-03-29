#!/usr/bin/env bash
set -euo pipefail

# Force-update Cortex plugin to the latest version.
#
# Claude Code caches plugin versions and doesn't always pick up updates
# from the marketplace. This script clears the stale cache and triggers
# a fresh install.
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/cdeust/Cortex/main/scripts/update-plugin.sh | bash

PLUGIN_DIR="$HOME/.claude/plugins"
CACHE_DIR="$PLUGIN_DIR/cache/cortex-plugins"
MARKETPLACE_DIR="$PLUGIN_DIR/marketplaces/cortex-plugins"
INSTALLED_JSON="$PLUGIN_DIR/installed_plugins.json"

echo "[cortex-update] Updating Cortex plugin..."

# Step 1: Pull latest marketplace
if [ -d "$MARKETPLACE_DIR/.git" ]; then
    echo "[cortex-update] Pulling latest from GitHub..."
    git -C "$MARKETPLACE_DIR" pull origin main --quiet 2>/dev/null || true
fi

# Step 2: Read new version from marketplace
NEW_VERSION=$(python3 -c "
import json
with open('$MARKETPLACE_DIR/.claude-plugin/plugin.json') as f:
    print(json.load(f)['version'])
" 2>/dev/null || echo "unknown")

echo "[cortex-update] Latest version: $NEW_VERSION"

# Step 3: Read current installed version
CURRENT_VERSION=$(python3 -c "
import json
with open('$INSTALLED_JSON') as f:
    d = json.load(f)
entries = d.get('plugins', {}).get('cortex@cortex-plugins', [{}])
print(entries[0].get('version', 'none') if entries else 'none')
" 2>/dev/null || echo "none")

echo "[cortex-update] Installed version: $CURRENT_VERSION"

if [ "$CURRENT_VERSION" = "$NEW_VERSION" ]; then
    echo "[cortex-update] Already up to date."
    exit 0
fi

# Step 4: Clear stale cache
if [ -d "$CACHE_DIR" ]; then
    echo "[cortex-update] Clearing stale cache at $CACHE_DIR..."
    rm -rf "$CACHE_DIR"
fi

# Step 5: Remove entry from installed_plugins.json
python3 -c "
import json
path = '$INSTALLED_JSON'
with open(path) as f:
    d = json.load(f)
if 'cortex@cortex-plugins' in d.get('plugins', {}):
    del d['plugins']['cortex@cortex-plugins']
    with open(path, 'w') as f:
        json.dump(d, f, indent=2)
    print('[cortex-update] Removed stale registry entry')
else:
    print('[cortex-update] No registry entry to remove')
" 2>/dev/null

# Step 6: Prompt user to reinstall
echo ""
echo "[cortex-update] Cache cleared. Now run:"
echo ""
echo "  claude plugin install cortex"
echo ""
echo "Then restart Claude Code to pick up v$NEW_VERSION."
