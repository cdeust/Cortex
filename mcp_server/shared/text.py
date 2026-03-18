"""Keyword extraction and text normalization for cognitive session analysis.

Two-tier filtering: tokens longer than 6 characters pass unconditionally (likely
meaningful), while shorter tokens (2-6 chars) must appear in TECHNICAL_SHORT_TERMS.
All standard English stopwords are excluded regardless of length.
"""

from __future__ import annotations

import re

TECHNICAL_SHORT_TERMS: frozenset[str] = frozenset(
    {
        "api",
        "sql",
        "jwt",
        "cli",
        "mcp",
        "git",
        "auth",
        "ssh",
        "ssl",
        "tls",
        "csv",
        "xml",
        "dom",
        "cdn",
        "dns",
        "tcp",
        "udp",
        "url",
        "uri",
        "http",
        "grpc",
        "cors",
        "crud",
        "orm",
        "rpc",
        "sdk",
        "npm",
        "prd",
        "cicd",
        "aws",
        "gcp",
        "k8s",
        "ci",
        "cd",
        "db",
        "io",
        "ui",
        "ux",
        "pr",
        "env",
        "pid",
        "llm",
        "rag",
        "gpu",
        "cpu",
        "ram",
        "ssd",
        "eof",
        "yml",
        "toml",
        "json",
        "html",
        "css",
        "wasm",
        "rust",
        "node",
        "deno",
        "bash",
        "zsh",
        "vim",
        "tmux",
        "redis",
        "kafka",
        "nginx",
        "hook",
        "cron",
        "mock",
        "stub",
        "lint",
        "type",
        "enum",
        "async",
    }
)

STOPWORDS: frozenset[str] = frozenset(
    {
        "the",
        "be",
        "to",
        "of",
        "and",
        "a",
        "in",
        "that",
        "have",
        "i",
        "it",
        "for",
        "not",
        "on",
        "with",
        "he",
        "as",
        "you",
        "do",
        "at",
        "this",
        "but",
        "his",
        "by",
        "from",
        "they",
        "we",
        "say",
        "her",
        "she",
        "or",
        "an",
        "will",
        "my",
        "one",
        "all",
        "would",
        "there",
        "their",
        "what",
        "so",
        "up",
        "out",
        "if",
        "about",
        "who",
        "get",
        "which",
        "go",
        "me",
        "when",
        "make",
        "can",
        "like",
        "time",
        "no",
        "just",
        "him",
        "know",
        "take",
        "people",
        "into",
        "year",
        "your",
        "good",
        "some",
        "could",
        "them",
        "see",
        "other",
        "than",
        "then",
        "now",
        "look",
        "only",
        "come",
        "its",
        "over",
        "think",
        "also",
    }
)

_SPLIT_RE = re.compile(r"\W+")


def extract_keywords(text: str | None) -> set[str]:
    """Extract meaningful keywords from text as a set.

    Splits on non-word characters, lowercases, then applies two-tier filtering:
    tokens >6 chars pass unconditionally, tokens 2-6 chars pass only if in
    TECHNICAL_SHORT_TERMS.
    """
    if not text:
        return set()
    return {
        w
        for w in _SPLIT_RE.split(text.lower())
        if len(w) > 6 or (len(w) >= 2 and w in TECHNICAL_SHORT_TERMS)
    }


def extract_keywords_array(text: str | None) -> list[str]:
    """Extract meaningful keywords from text as a list."""
    return list(extract_keywords(text))
