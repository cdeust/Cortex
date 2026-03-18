---
name: methodology
description: View your cognitive methodology profile and reasoning patterns
---

Use the `methodology-agent:query_methodology` tool with the current working directory to retrieve the user's cognitive profile for this domain.

Display the `context` field as a summary paragraph, then offer:
1. Run `methodology-agent:rebuild_profiles` if the profile seems stale or the user wants a fresh analysis
2. Run `methodology-agent:list_domains` to show all detected domains
3. Run `methodology-agent:get_methodology_graph` to get visualization data

If no profile exists yet, run `methodology-agent:rebuild_profiles` first to build one from session history.
