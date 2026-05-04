# arXiv Endorsement Request — Direct Email Template

Use this when reaching an academic endorser through a personal/colleague intro
(e.g. colleague's husband). The framing is "I have a finished preprint ready
to upload, I just need the arXiv-policy endorsement signature, here is what
you'd be signing off on."

---

## Subject line

`arXiv endorsement request — long-term memory for AI agents (cs.IR or cs.CL)`

## Body

Dear [Name],

[Your colleague]'s wife mentioned you publish on arXiv and might be willing to
consider an endorsement request. I'm an independent researcher (15 years in
mobile engineering, the last 18 months on AI infrastructure) and I have two
preprints ready for arXiv that need an endorser before submission.

Both papers are about long-term memory for LLM agents — a new and active topic
where current systems collapse at multi-million-token scale. The work is fully
reproducible, MIT-licensed, and the production code is on GitHub at
github.com/cdeust/Cortex (★26, growing — Perplexity surfaces it on
"persistent memory for Claude Code" queries).

**Paper 1 — Stage-Aware Context Assembly for Long-Context Memory Retrieval** (cs.IR)
- 22 pages, ready to submit
- Headline: +33.4% MRR over flat retrieval on BEAM-10M (ICLR 2026 benchmark, the hardest long-context memory test in the field)
- The architecture beats the oracle-label version using only timestamps — temporal proximity turns out to be a stronger retrieval signal than ground-truth topic boundaries
- Designed September 2025 (verifiable commit history) — predates the BEAM paper

**Paper 2 — Thermodynamic Memory vs. Flat-Importance Stores** (cs.IR or cs.CL)
- 30 pages, ready to submit
- 45 row per-mechanism ablation campaign on LongMemEval (n=500) and LoCoMo (n=1986)
- LongMemEval R@10 98.4% (vs 78.4% paper best), LoCoMo R@10 94.2%
- Verification surfaced two real production bugs that were fixed and disclosed in the paper itself — the verification campaign improved the system, not just measured it

Both PDFs:
- github.com/cdeust/Cortex/blob/main/docs/arxiv-thermodynamic/main.pdf
- github.com/cdeust/Cortex/blob/main/docs/arxiv-context-assembly/main.pdf

What I'd need from you, if you're willing: log in to arxiv.org, paste my
endorsement code (I'll send it once I create the account), and click endorse.
That's the entire ask. arXiv's policy is that you're vouching the work is
appropriate for arXiv (not crank, not spam) — not peer-review-quality
endorsement. The endorsement carries forward to all my future submissions
in the category, so it's a one-time gate.

I'd be delighted to share more context, jump on a 15-minute call, or answer
any questions before you decide. The papers are honest, reproducible, and
self-contained — every constant traces to a paper or measured ablation.

Thank you very much for considering,

Clément Deust
clement.deust@gmail.com
github.com/cdeust/Cortex

---

## Pre-submission checklist (run through before requesting endorsement)

| Item | Status | Notes |
|---|---|---|
| arXiv account created | TBD | arxiv.org/user/register — needs ORCID optional |
| Email verified | TBD | arXiv sends a confirmation link |
| Affiliation set in profile | TBD | "Independent Researcher" is acceptable |
| Endorsement code generated | TBD | Visible after `submit-paper` flow starts |
| Both PDFs compile clean with bibtex | DONE | 30pp / 22pp, all citations resolve |
| Author block has name + affiliation | DONE | "Clement Deust / Independent Researcher" |
| Code-availability footnote present | DONE | links to github.com/cdeust/Cortex |
| MIT license on repo | DONE | LICENSE file at root |
| References.bib complete (no missing entries) | DONE | 45 cites, 0 undefined warnings |

## What arXiv will ask at submission time (not in the .tex)

- Primary subject category: cs.IR (Information Retrieval) recommended for both papers.
- Cross-list categories: cs.CL (Computation and Language), cs.AI (Artificial Intelligence).
- License selection: CC BY 4.0 recommended (matches MIT spirit, lets others reuse with attribution). CC BY-NC-SA also fine.
- Comments field: include a short reproducibility line — "Code, data, and 45-row ablation results at github.com/cdeust/Cortex (commit <SHA>)."

## When to send

- If the endorser is reachable through a warm intro (colleague's husband), wait until your colleague has actually mentioned the paper to him so you're not cold.
- Best moment is right after he's seen at least the abstract or repo description — you want him to be already mildly curious, not just walking in cold.

## What NOT to do

- Don't apologize for asking — endorsement is a two-minute click, not a peer review.
- Don't send the full paper as a PDF attachment; link to GitHub instead. Endorsers prefer in-browser preview.
- Don't pre-emptively send the endorsement code; wait for him to confirm willingness.
- Don't ask for endorsement on multiple categories from the same person — one endorsement per category, separate requests.
