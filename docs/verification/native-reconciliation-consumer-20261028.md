# Native gate reconciliation consumer verification

Canonical source: https://github.com/cdeust/zetetic-team-subagents/pull/200 at ddbc41266a9d6c031a5c5891eead745138265e9f. Helper SHA256: 2ea7d95920ef289219ee1796ce7de38e68233464c81d74d3b8fa81fd2108a9a8. Codex.yml SHA256: db5b3aa7b0ba336cc690332ae6a89e16b2a94900c65898925315029564b1c1fb. Production files match those canonical bytes.

The fallback reads trusted default-branch code, checks current native proof and reuses exact gate-resumption policy. Its five-minute schedule and manual workflow dispatch are supported Actions events. It invokes no models, uses the existing PR concurrency group and adds no merge gate. Ordinary native-summary events keep their existing path. GitHub schedules can be delayed. Source: https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule .

Cortex: 277 local CI contracts passed after integration. The parser-only followup passed its focused contracts; actionlint and shell syntax checks passed. Hosted scheduled acceptance must follow installation on main. No bot event or review was fabricated.
