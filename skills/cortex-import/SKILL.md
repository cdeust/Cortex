---
name: cortex-import
description: "Import memories from other AI memory systems into Cortex. Supports claude-mem (SQLite), Claude Desktop sessions, ChatGPT web export (JSON), Gemini Takeout (JSON), Cursor conversations, and Claude Code JSONL. Use when the user says 'import from claude-mem', 'migrate memories', 'import ChatGPT history', 'import from Gemini', 'transfer memories', or when Cortex detects another memory system is installed."
---

# Import Memories — Multi-Source Migration

Detect available memory sources and import them into Cortex. Run fully autonomously — detect, import, consolidate.

## Phase 1: Source Detection

Run this bash command to detect all sources:

```bash
echo "=== Memory Sources ==="

# 1. Claude Code JSONL
CC=$(find ~/.claude/projects -name "*.jsonl" 2>/dev/null | wc -l | tr -d ' ')
echo "Claude Code JSONL: $CC files"

# 2. Claude Desktop sessions
CD=$(find ~/Library/Application\ Support/Claude/claude-code-sessions -name "*.json" 2>/dev/null | wc -l | tr -d ' ')
echo "Claude Desktop: $CD session files"

# 3. claude-mem
if [ -f ~/.claude-mem/claude-mem.db ]; then
    CM=$(sqlite3 ~/.claude-mem/claude-mem.db "SELECT COUNT(*) FROM observations" 2>/dev/null || echo "0")
    echo "claude-mem: $CM observations"
else
    echo "claude-mem: not found"
fi

# 4. ChatGPT — desktop app stores binary, need web export
CHATGPT=$(find ~/Downloads -name "conversations.json" -maxdepth 3 2>/dev/null | head -1)
if [ -n "$CHATGPT" ]; then
    echo "ChatGPT export: $CHATGPT"
else
    echo "ChatGPT: no export (get from chatgpt.com → Settings → Data controls → Export)"
fi

# 5. Gemini Takeout
GEMINI=$(find ~/Downloads -path "*Gemini*" -name "*.json" -maxdepth 5 2>/dev/null | head -1)
if [ -n "$GEMINI" ]; then
    echo "Gemini export: $GEMINI"
else
    echo "Gemini: no export (get from takeout.google.com → select Gemini Apps)"
fi

# 6. Cursor
if [ -d ~/.cursor ]; then
    CU=$(find ~/.cursor -name "*.jsonl" 2>/dev/null | wc -l | tr -d ' ')
    echo "Cursor: $CU files"
else
    echo "Cursor: not installed"
fi
```

Report findings, then proceed with each detected source.

## Phase 2: Claude Code Import

If Claude Code JSONL files exist (always the case):

```
cortex:backfill_memories({"max_files": 500, "min_importance": 0.3, "force_reprocess": false})
```

## Phase 3: claude-mem Import

If `~/.claude-mem/claude-mem.db` exists, run:

```bash
DEPS_DIR="$HOME/.claude/plugins/data/cortex-cortex-plugins/deps"
PYTHONPATH="${CLAUDE_PLUGIN_ROOT:-/Users/cdeust/.claude/plugins/marketplaces/cortex-plugins}:$DEPS_DIR" \
DATABASE_URL="${DATABASE_URL:-postgresql://localhost:5432/cortex}" \
python3 -c "
import sqlite3, json, asyncio, sys, os

db_path = os.path.expanduser('~/.claude-mem/claude-mem.db')
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
rows = conn.execute('SELECT type, title, narrative, facts, concepts, created_at_epoch, project FROM observations ORDER BY created_at_epoch').fetchall()
print(f'Found {len(rows)} claude-mem observations')

from mcp_server.handlers.remember import handler as remember_handler
from datetime import datetime, timezone
imported = 0
for row in rows:
    parts = []
    if row['title']: parts.append(row['title'])
    if row['narrative']: parts.append(row['narrative'])
    if row['facts']:
        try:
            for f in json.loads(row['facts']): parts.append(str(f))
        except: pass
    content = '\n'.join(parts)
    if len(content) < 20: continue
    tags = ['imported', 'claude-mem']
    if row['type']: tags.append(row['type'])
    if row['concepts']:
        try: tags.extend(json.loads(row['concepts'])[:5])
        except: pass
    created_at = None
    if row['created_at_epoch']:
        try: created_at = datetime.fromtimestamp(row['created_at_epoch'], tz=timezone.utc).isoformat()
        except: pass
    result = asyncio.run(remember_handler({'content': content, 'tags': tags, 'domain': row['project'] or '', 'source': 'claude-mem', 'force': True, 'created_at': created_at}))
    if result.get('stored'): imported += 1
print(f'Imported {imported} memories from claude-mem')
conn.close()
"
```

## Phase 4: ChatGPT Import

If a `conversations.json` file was found in Downloads, or the user provides one:

```bash
DEPS_DIR="$HOME/.claude/plugins/data/cortex-cortex-plugins/deps"
PYTHONPATH="${CLAUDE_PLUGIN_ROOT:-/Users/cdeust/.claude/plugins/marketplaces/cortex-plugins}:$DEPS_DIR" \
DATABASE_URL="${DATABASE_URL:-postgresql://localhost:5432/cortex}" \
python3 -c "
import json, asyncio, sys, os
path = 'REPLACE_WITH_PATH_TO_CONVERSATIONS_JSON'
with open(path) as f: data = json.load(f)
from mcp_server.handlers.remember import handler as remember_handler
from datetime import datetime, timezone
imported = 0
for conv in data:
    title = conv.get('title', '')
    for nid, node in (conv.get('mapping') or {}).items():
        msg = node.get('message') or {}
        if not msg: continue
        role = (msg.get('author') or {}).get('role', '')
        if role not in ('user', 'assistant'): continue
        parts = msg.get('content', {}).get('parts', [])
        text = '\n'.join(str(p) for p in parts if isinstance(p, str))
        if len(text) < 30: continue
        created_at = None
        ct = msg.get('create_time')
        if ct:
            try: created_at = datetime.fromtimestamp(ct, tz=timezone.utc).isoformat()
            except: pass
        result = asyncio.run(remember_handler({'content': text[:4000], 'tags': ['imported', 'chatgpt', role], 'domain': title[:50] or 'chatgpt', 'source': 'chatgpt', 'force': False, 'created_at': created_at}))
        if result.get('stored'): imported += 1
print(f'Imported {imported} memories from ChatGPT')
"
```

If no export file exists, tell the user:
> ChatGPT desktop app stores conversations in binary format — not readable. To import, export from the web:
> 1. Go to **chatgpt.com → Settings → Data controls → Export data**
> 2. Wait for the email with the download link
> 3. Unzip to ~/Downloads/
> 4. Run `/cortex-import` again

## Phase 5: Gemini Import

If Gemini Takeout JSON files found, scan the `Gemini Apps/` folder for conversation JSON:

```bash
DEPS_DIR="$HOME/.claude/plugins/data/cortex-cortex-plugins/deps"
PYTHONPATH="${CLAUDE_PLUGIN_ROOT:-/Users/cdeust/.claude/plugins/marketplaces/cortex-plugins}:$DEPS_DIR" \
DATABASE_URL="${DATABASE_URL:-postgresql://localhost:5432/cortex}" \
python3 -c "
import json, asyncio, sys, os, glob
gemini_dir = 'REPLACE_WITH_PATH_TO_GEMINI_TAKEOUT'
files = glob.glob(os.path.join(gemini_dir, '**/*.json'), recursive=True)
from mcp_server.handlers.remember import handler as remember_handler
imported = 0
for fp in files:
    try:
        with open(fp) as f: data = json.load(f)
    except: continue
    if not isinstance(data, list): data = [data]
    for item in data:
        parts = item.get('parts', [])
        for part in parts:
            text = part.get('text', '')
            if len(text) < 30: continue
            result = asyncio.run(remember_handler({'content': text[:4000], 'tags': ['imported', 'gemini'], 'domain': 'gemini', 'source': 'gemini', 'force': False}))
            if result.get('stored'): imported += 1
print(f'Imported {imported} memories from Gemini')
"
```

If no Gemini export exists:
> To import Gemini conversations:
> 1. Go to **takeout.google.com**
> 2. Deselect all, then select **Gemini Apps**
> 3. Download and unzip to ~/Downloads/
> 4. Run `/cortex-import` again

## Phase 6: Consolidation

After all imports:

```
cortex:consolidate({})
cortex:memory_stats({})
```

## Final Summary

Print one summary block with all results.
