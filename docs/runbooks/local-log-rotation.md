# Local log rotation and legacy-file migration

`telemetry.jsonl`, `consolidate.log`, and `pipeline_reanalyze.log` retain an
active file and one previous segment named `.1`. The threshold is 5,880,000
bytes: F9 measured 196 kB/day on 2026-09-06, multiplied by the 30-day interval
specified in `tasks/codex-green-remediation-plan.md`, W2-3. This is a size
policy derived from that observation, not a guaranteed retention duration.

Telemetry checks before each UTF-8 append. A record is kept whole, even if a
single record exceeds the threshold. Its in-memory counters continue across
rotation. A stable `.lock` sidecar serializes cooperating writers across
processes; do not remove that file while writers are running. This follows the
[Python warning about multiprocess file handlers](https://docs.python.org/3/howto/logging-cookbook.html#logging-to-a-single-file-from-multiple-processes).

Workers rotate before spawning. Their inherited stdout/stderr descriptors
remain open until they exit, so an active worker can exceed the threshold or
keep writing to `.1` after another spawn rotates it. This is not a hard disk
quota. On Windows an open file can prevent renaming; the existing hook failure
boundary reports the error. No additional collector process is introduced.
The parent closes its own log descriptor after `Popen` returns.

The initial rotation preserves the entire existing file as `.1`, even if it is
already larger than the threshold. A later rotation replaces that previous
segment. Archive existing logs before enabling this version if their full
history must be retained. No historical files were rotated during development.

## Legacy migration — owner only

At the implementation baseline, `rg -n -F 'session_log.json' mcp_server scripts`
already returned no matches; there is no `hooks/` directory at the repository
root. There is no remaining legacy reader or writer to remove. The canonical
path is `session-log.json` in
`mcp_server/infrastructure/config.py`; `session_store.py` serves its readers
and writers. No compatibility shim is added.

The old file may still exist on an owner's machine. After stopping Cortex
sessions, the owner can run this one-shot command with an explicit root. It
only removes an ordinary legacy file whose parsed JSON exactly matches the
canonical file, preserving JSON types and refusing non-finite numbers.
Different or malformed content requires manual reconciliation;
the command refuses rather than merging or discarding unknown data.

```bash
CORTEX_CLAUDE_DIR=/absolute/claude-root python3 - <<'PY'
import json
import os
from pathlib import Path

def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SystemExit(f"Refused: duplicate JSON key {key}")
        result[key] = value
    return result

root = Path(os.environ["CORTEX_CLAUDE_DIR"])
if not root.is_absolute() or ".." in root.parts:
    raise SystemExit("Refused: provide an absolute root without '..'")
folder = root / "methodology"
for path in (folder, *folder.parents):
    if path.is_symlink():
        raise SystemExit(f"Refused: symlink ancestor {path}")
legacy = folder / "session_log.json"
canonical = folder / "session-log.json"
for path in (legacy, canonical):
    if path.is_symlink() or not path.is_file():
        raise SystemExit(f"Refused: expected an ordinary existing file: {path}")
def canonical_json(path):
    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_keys)
    return json.dumps(value, sort_keys=True, allow_nan=False)

old = canonical_json(legacy)
new = canonical_json(canonical)
if old != new:
    raise SystemExit("Refused: contents differ; reconcile them manually")
legacy.unlink()
print(f"Removed verified duplicate: {legacy}")
PY
```

This migration is not run at startup or during installation. No production
directory was inspected, and no freed-space or energy reduction is claimed.
