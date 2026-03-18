"""Text scoring signals: BM25, n-gram phrase matching, keyword overlap.

BM25 parameters match ai-architect's PostgreSQL ts_rank (k1=1.5, b=0.75).
N-gram weights match ai-architect config (trigram=0.4, bigram=0.35, content=0.25).

Pure business logic -- no I/O.
"""

from __future__ import annotations

import math
import re
from collections import Counter


_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "to",
        "of",
        "and",
        "or",
        "in",
        "on",
        "at",
        "for",
        "with",
        "by",
        "from",
        "it",
        "this",
        "that",
        "do",
        "did",
        "does",
        "what",
        "when",
        "where",
        "why",
        "how",
        "who",
        "which",
        "can",
        "could",
        "would",
        "should",
        "will",
        "about",
        "tell",
        "me",
        "my",
        "i",
        "you",
        "your",
        "we",
    }
)


def tokenize(text: str) -> list[str]:
    """Whitespace + punctuation tokenizer with stopword filtering."""
    return [w for w in re.findall(r"\w+", text.lower()) if w not in _STOPWORDS]


def tokenize_raw(text: str) -> list[str]:
    """Tokenizer without stopword filtering (for BM25 term frequency)."""
    return re.findall(r"\w+", text.lower())


def _build_bm25_stats(
    documents: list[str],
) -> tuple[list[list[str]], list[int], float, Counter, int]:
    """Pre-compute BM25 corpus statistics."""
    doc_tokens = [tokenize_raw(d) for d in documents]
    doc_lengths = [len(t) for t in doc_tokens]
    avg_dl = sum(doc_lengths) / len(doc_lengths) if doc_lengths else 1.0
    df: Counter = Counter()
    for tokens in doc_tokens:
        for term in set(tokens):
            df[term] += 1
    return doc_tokens, doc_lengths, avg_dl, df, len(documents)


def _bm25_doc_score(
    q_terms: list[str],
    tokens: list[str],
    dl: int,
    avg_dl: float,
    df: Counter,
    n: int,
    k1: float,
    b: float,
) -> float:
    """Score a single document against query terms."""
    tf_map = Counter(tokens)
    score = 0.0
    for term in q_terms:
        if term not in tf_map:
            continue
        tf = tf_map[term]
        idf = math.log((n - df[term] + 0.5) / (df[term] + 0.5) + 1.0)
        score += idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avg_dl))
    return score


def compute_bm25_scores(
    query: str,
    documents: list[str],
    k1: float = 1.5,
    b: float = 0.75,
) -> list[float]:
    """BM25 scores normalized to [0, 1]. Okapi BM25 with IDF smoothing."""
    q_terms = tokenize_raw(query)
    if not q_terms or not documents:
        return [0.0] * len(documents)
    doc_tokens, doc_lengths, avg_dl, df, n = _build_bm25_stats(documents)
    scores = [
        _bm25_doc_score(q_terms, doc_tokens[i], doc_lengths[i], avg_dl, df, n, k1, b)
        for i in range(n)
    ]
    mx = max(scores) if scores else 1.0
    return [s / mx if mx > 0 else 0.0 for s in scores]


def _extract_ngrams(tokens: list[str], n: int) -> set[tuple[str, ...]]:
    """Extract character n-grams from token sequence."""
    if len(tokens) < n:
        return set()
    return {tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}


def compute_keyword_overlap(query: str, document: str) -> float:
    """Simple keyword overlap ratio."""
    q_terms = set(tokenize_raw(query))
    d_terms = set(tokenize_raw(document))
    if not q_terms:
        return 0.0
    return len(q_terms & d_terms) / len(q_terms)


def compute_ngram_score(query: str, document: str) -> float:
    """Combined trigram + bigram + content-word overlap score.

    Weights: trigram=0.4, bigram=0.35, content_word=0.25
    (matches ai-architect config).
    """
    q_tok = tokenize_raw(query)
    d_tok = tokenize_raw(document)
    if not q_tok or not d_tok:
        return 0.0

    q_tri = _extract_ngrams(q_tok, 3)
    d_tri = _extract_ngrams(d_tok, 3)
    tri = len(q_tri & d_tri) / max(len(q_tri), 1) if q_tri else 0.0

    q_bi = _extract_ngrams(q_tok, 2)
    d_bi = _extract_ngrams(d_tok, 2)
    bi = len(q_bi & d_bi) / max(len(q_bi), 1) if q_bi else 0.0

    q_cw = {t for t in q_tok if t not in _STOPWORDS and len(t) > 2}
    d_cw = {t for t in d_tok if t not in _STOPWORDS}
    cw = len(q_cw & d_cw) / max(len(q_cw), 1) if q_cw else 0.0

    return 0.4 * tri + 0.35 * bi + 0.25 * cw
