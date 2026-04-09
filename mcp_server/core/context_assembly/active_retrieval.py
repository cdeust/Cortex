"""Active retrieval — generate a refined sub-query before recall fires.

**Paper backing**:
  Wang & Chen, "MIRIX: Multi-Agent Memory System for LLM-Based Agents",
  arxiv 2507.07957 (July 2025). § Active Retrieval: the agent generates
  a topic/sub-query from the raw question, retrieves on the refined
  query, and injects the result into the system prompt. Reported 85.4%
  on LoCoMo.

**Why this matters for BEAM**: probing questions are rarely phrased the
way stored content is. A question like "when did I first mention X?"
does not lexically or semantically match "I think X is important
because ..." written 9000 turns ago. Reformulating the question into a
search-optimized form bridges the gap.

**Implementation**: two strategies provided.
  - `KeywordExtractor`: rule-based — pull nouns, proper nouns, temporal
    expressions, and any quoted strings. Zero latency, no model.
  - `LLMReformulator`: calls a small local model (e.g. Apple FM or a
    lightweight transformer) to rewrite the question. Slower, more
    accurate. Gated by model availability.

Cortex's `query_decomposition.py` already does entity extraction; this
module is the query-side counterpart.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any


class ActiveRetriever(ABC):
    """Rewrites a raw query into a search-optimized form."""

    @abstractmethod
    def reformulate(self, query: str) -> str:
        """Return a reformulated query (or the original if no change)."""


# ── Rule-based reformulator ─────────────────────────────────────────────


class KeywordExtractor(ActiveRetriever):
    """Extract high-signal keywords; drop question words and filler.

    Fast, deterministic, no model required. Good baseline against
    which to A/B test LLM-based reformulation.
    """

    _QUESTION_WORDS = {
        "what",
        "when",
        "where",
        "who",
        "why",
        "how",
        "which",
        "whose",
        "whom",
        "does",
        "did",
        "is",
        "was",
        "are",
        "were",
        "can",
        "could",
        "will",
        "would",
        "should",
        "have",
        "has",
        "had",
        "do",
        "the",
        "a",
        "an",
        "i",
        "you",
        "me",
        "my",
        "your",
        "our",
        "they",
        "them",
        "us",
        "he",
        "she",
        "it",
        "its",
        "be",
        "been",
        "being",
        "to",
        "of",
        "in",
        "on",
        "at",
        "by",
        "for",
        "with",
        "about",
        "against",
        "between",
        "into",
        "through",
        "during",
        "before",
        "after",
    }

    _DATE_RE = re.compile(
        r"\b(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}|"
        r"(january|february|march|april|may|june|july|august|"
        r"september|october|november|december)\s+\d{1,2}(?:,?\s+\d{4})?)\b",
        re.IGNORECASE,
    )

    def reformulate(self, query: str) -> str:
        if not query.strip():
            return query

        # Preserve quoted strings verbatim
        quoted = re.findall(r"'([^']+)'|\"([^\"]+)\"", query)
        quoted_terms = [q[0] or q[1] for q in quoted]

        # Preserve dates
        dates = [m.group(0) for m in self._DATE_RE.finditer(query)]

        # Extract capitalized words (likely proper nouns) and words of length >= 4
        words = re.findall(r"\b[\w']+\b", query)
        keywords: list[str] = []
        for w in words:
            wl = w.lower()
            if wl in self._QUESTION_WORDS:
                continue
            if w[0].isupper() or len(w) >= 4:
                keywords.append(w)

        combined = quoted_terms + dates + keywords
        if not combined:
            return query
        # Preserve original order roughly, dedupe
        seen: set[str] = set()
        out: list[str] = []
        for term in combined:
            if term.lower() not in seen:
                seen.add(term.lower())
                out.append(term)
        return " ".join(out)


# ── LLM-based reformulator (optional) ──────────────────────────────────


class LLMReformulator(ActiveRetriever):
    """Use a small local model to rewrite the query.

    Gated: if no LLM is available, falls back to passthrough. The
    caller is responsible for providing a `llm_fn` that takes a prompt
    and returns a completion. This keeps the module dependency-free.
    """

    _REFORMULATION_PROMPT = (
        "Rewrite the following question as a search query optimized for "
        "retrieving relevant passages from a conversation log. Keep key "
        "entities, dates, and specific terms. Drop filler. Return ONLY "
        "the rewritten query, no preamble.\n\n"
        "Question: {query}\n"
        "Rewritten query:"
    )

    def __init__(self, llm_fn: Any | None = None) -> None:
        self._llm_fn = llm_fn

    def reformulate(self, query: str) -> str:
        if self._llm_fn is None:
            return query
        try:
            prompt = self._REFORMULATION_PROMPT.format(query=query)
            result = self._llm_fn(prompt)
            if isinstance(result, str) and result.strip():
                return result.strip()
        except Exception:
            pass
        return query
