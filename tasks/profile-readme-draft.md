# cdeust/cdeust GitHub Profile README — draft

This file is a draft for the GitHub profile README that should live at
`github.com/cdeust/cdeust/blob/main/README.md`. The profile repo does not
exist yet (user authorization needed to create the public repo).

To activate:
```bash
gh repo create cdeust/cdeust --public --add-readme
cd cdeust
# replace the auto-generated README with the body below
git add README.md
git commit -m "feat: profile README"
git push origin main
```

The body below is what AI Overview / Perplexity / similar AI search will
parse when someone queries `cdeust` or `Clément Deust`. It puts the
right projects in the right order and anchors the benchmark numbers to
the right repo.

---

# Clément Deust

Building AI infrastructure. 15 years shipping mobile software.

## Active projects

### [Cortex](https://github.com/cdeust/Cortex) — persistent memory for Claude Code
Long-term memory system for AI agents. PostgreSQL + pgvector, 26 biological mechanisms with paper-bearing per-mechanism ablation evidence. Beats published baselines on three benchmarks:

- **LongMemEval (ICLR 2025):** R@10 98.4%, MRR 0.9124 (n=500) vs published 78.4% / —
- **LoCoMo (ACL 2024):** R@10 94.2%, MRR 0.8278 (n=1986) vs published — / 0.794
- **BEAM-10M (ICLR 2026):** +33.4% over flat retrieval (0.471 vs 0.353)

Verified via 31-row two-benchmark ablation campaign (`tasks/e1-v3-results.md`, `tasks/e1-v3-locomo-results.md`). Paper draft: `docs/arxiv-thermodynamic/main.pdf`.

### [PRD Spec Generator](https://github.com/cdeust/prd-spec-generator) — verified PRD reducer
Stateless reducer that turns a feature description into a 9-file PRD. 17 MCP tools, multi-judge verification with weighted-average + Bayesian consensus, deterministic Hard Output Rules, 248 tests. Part of the AI Architect ecosystem.

### [Automatised Pipeline](https://github.com/cdeust/automatised-pipeline) — codebase intelligence
Codebase intelligence as an MCP server. Tree-sitter AST → LadybugDB graph → Louvain communities → hybrid BM25 + TF-IDF + RRF search. 23 tools, 10 stages, 220 tests, Rust, Clean Architecture. The read-only intelligence layer between finding and PRD.

### [AI Architect](https://ai-architect.tools) — autonomous engineering pipeline
11-stage orchestration over Cortex + PRD Spec Generator + Automatised Pipeline: finding → spec → verified PR with no LLM judges. 64 verification rules, 17 codebase intelligence tools, 5 science-backed git analytics.

## What I believe

AI-generated code is only as good as the specification it implements. Skip the spec, ship the bugs. That's why everything I build starts with verification — not as a feature, but as the architecture.

## Contact
[GitHub](https://github.com/cdeust) · [LinkedIn](https://linkedin.com/in/cdeust) · [ai-architect.tools](https://ai-architect.tools)
