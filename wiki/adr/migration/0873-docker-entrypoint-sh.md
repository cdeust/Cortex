---
title: "ADR-0873 — docker/entrypoint.sh rationale"
status: accepted
source: docker/entrypoint.sh
---

# ADR-0873 — docker/entrypoint.sh

Source rationale preserved verbatim. Identifiers inside historical quotations are not current identities.

## docker/entrypoint.sh — original line 141

````text
# ── Step 4b: Install Cortex hooks (as cortex user so ~/.claude resolves correctly) ──
````

## Final non-Python residual audit

### docker/entrypoint.sh — pre-cleanup line 59

````text
    # Only copy credentials — NOT settings.json (contains host-specific hooks/paths)
````
