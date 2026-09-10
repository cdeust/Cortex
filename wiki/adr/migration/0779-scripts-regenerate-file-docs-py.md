# ADR-0779: scripts/regenerate_file_docs.py implementation decisions

Status: accepted; preserved from the existing implementation during issue #514.

These are historical implementation records, not new algorithm or threshold choices.
Source: `scripts/regenerate_file_docs.py`; original SHA-256 `4714b7e74d949951c993286477c79a6e3875d200918dc04eddf3b7699037df39`.

## Original docstring, lines 2–27

````text
"""Regenerate wiki file-doc skeletons for every project.

The 2026-05-18 shallow-purge incident deleted 8 629 auto-generated
file-doc pages because they had under 500 chars of real prose. The
user correction was explicit: *deletion is not curation*. The right
move is to keep one skeleton per source file with EVERY missing
section visible — so the reader sees what's not yet documented and the
LLM has a concrete queue to drain.

This script:

  1. Discovers every git-tracked project under the configured dev
     roots (via ``shared.domain_mapping``).
  2. For each project + each source file, generates a wiki page at
     ``reference/<domain>/<flattened-path>.md`` via
     ``core.wiki_file_doc_skeleton.build_file_doc``.
  3. Skips files that already have a substantive page (>= 1500 chars
     of real prose) — we don't want to overwrite hand-curated work.
  4. Reports counts per project.

Usage::

    PYTHONPATH=<cortex-root> python3 scripts/regenerate_file_docs.py [--apply]

Without ``--apply`` it's a dry-run that prints what would be generated.
"""
````

## Original comment, lines 50–51

````text
# source: pre-existing tuned value, extracted unchanged (#197 family 3);
# provenance not recorded at introduction
````

