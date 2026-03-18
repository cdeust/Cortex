"""Concept expansion vocabulary for query enrichment.

Maps concepts to related terms across two domains:
  - Programming & DevOps (code, architecture, ML, infra)
  - Personal & Lifestyle (preferences, facts, activities, health, travel)

Used by enrichment.py for retrieval-time query expansion.
Pure data -- no logic.
"""

from __future__ import annotations

CONCEPT_MAP: dict[str, list[str]] = {
    # ── Programming & DevOps ──────────────────────────────────────────
    "memory": ["cache", "storage", "store", "recall", "retrieve", "persist"],
    "cache": ["memory", "buffer", "store", "memoize", "ttl"],
    "database": ["db", "sqlite", "postgres", "mysql", "storage", "persistence"],
    "vector": ["embedding", "semantic", "similarity", "ndarray", "tensor"],
    "function": ["def", "method", "callable", "handler", "procedure"],
    "test": ["pytest", "unittest", "assert", "spec", "coverage"],
    "error": ["exception", "traceback", "failure", "bug", "crash", "issue"],
    "bug": ["error", "defect", "regression", "failure", "fix"],
    "fix": ["patch", "resolve", "repair", "correct", "debug"],
    "architecture": ["design", "pattern", "structure", "layout", "module"],
    "refactor": ["restructure", "reorganize", "clean up", "simplify", "decouple"],
    "api": ["endpoint", "interface", "rest", "rpc", "http", "service"],
    "async": ["await", "coroutine", "concurrent", "parallel", "event loop"],
    "embedding": ["vector", "encode", "sentence-transformer", "semantic", "represent"],
    "model": ["neural network", "transformer", "classifier", "llm", "fine-tune"],
    "inference": ["predict", "forward pass", "generate", "decode"],
    "deploy": ["release", "ship", "publish", "launch", "push"],
    "config": ["configuration", "settings", "env", "environment variable"],
    "docker": ["container", "image", "compose", "kubernetes"],
    "ci": ["github actions", "workflow", "pipeline", "build"],
    "import": ["module", "package", "dependency", "pip", "install"],
    "decorator": ["wrapper", "middleware", "aspect", "@"],
    "type hint": ["annotation", "typing", "pydantic", "dataclass"],
    "commit": ["git", "push", "branch", "merge", "pull request", "pr"],
    "merge": ["rebase", "squash", "conflict", "branch"],
    # ── Personal & Lifestyle ──────────────────────────────────────────
    "favorite": [
        "like",
        "love",
        "prefer",
        "enjoy",
        "best",
        "fond",
        "into",
        "favourite",
    ],
    "prefer": ["favorite", "like", "love", "choice", "go-to", "preferred", "rather"],
    "recommend": [
        "suggest",
        "suggestion",
        "advice",
        "try",
        "check",
        "favorite",
        "like",
    ],
    "like": ["enjoy", "love", "prefer", "fan", "fond", "into"],
    "enjoy": ["like", "love", "prefer", "fan", "fond", "into", "fun"],
    "hobby": ["hobbies", "pastime", "interest", "enjoy", "free time", "leisure"],
    "sport": ["sports", "team", "playing", "exercise", "workout", "gym", "running"],
    "exercise": ["workout", "gym", "fitness", "running", "yoga", "training"],
    "game": ["gaming", "play", "playing", "video game", "board game", "console"],
    "book": ["reading", "read", "novel", "author", "story", "literature", "genre"],
    "movie": ["film", "watch", "watched", "cinema", "theater", "show", "series", "tv"],
    "playlist": ["music", "songs", "spotify", "listen", "band", "artist", "album"],
    "recipe": ["cook", "cooking", "bake", "baking", "dish", "meal", "ingredient"],
    "restaurant": ["eat", "dining", "dine", "food", "cuisine", "cafe"],
    "job": [
        "work",
        "career",
        "occupation",
        "profession",
        "role",
        "position",
        "employer",
    ],
    "live": ["living", "reside", "home", "address", "house", "apartment", "moved"],
    "name": ["called", "named", "goes"],
    "pet": ["dog", "cat", "animal", "puppy", "kitten", "fish", "bird"],
    "born": ["birthday", "birth", "age", "years old"],
    "married": ["wife", "husband", "spouse", "partner", "wedding", "engaged"],
    "children": ["kids", "son", "daughter", "child", "baby", "toddler"],
    "sibling": ["brother", "sister", "siblings"],
    "parent": ["mother", "father", "mom", "dad", "parents"],
    "degree": ["graduated", "university", "college", "school", "major", "studied"],
    "learn": ["learning", "study", "studying", "course", "tutorial", "practice"],
    "class": ["course", "lesson", "lecture", "seminar", "workshop", "training"],
    "resource": ["tutorial", "course", "guide", "documentation", "book", "video"],
    "doctor": ["appointment", "medical", "health", "clinic", "hospital", "checkup"],
    "allergic": ["allergy", "allergies", "intolerant", "intolerance", "sensitive"],
    "diet": ["eating", "food", "nutrition", "meal", "healthy", "weight"],
    "travel": ["trip", "vacation", "holiday", "visit", "flew", "flight", "destination"],
    "commute": ["drive", "driving", "train", "bus", "subway", "walk", "bike"],
    "car": ["vehicle", "drive", "driving", "auto", "truck"],
    "buy": ["bought", "purchased", "ordered", "got", "picked"],
    "bought": ["buy", "purchased", "ordered", "got", "picked"],
    "wear": ["wearing", "wore", "outfit", "clothes", "shirt", "dress"],
    "currently": ["now", "recent", "latest", "present", "today"],
    "recently": ["lately", "just", "new", "recent", "last"],
    "changed": ["switched", "moved", "updated", "new", "different"],
}


def build_reverse_map(concept_map: dict[str, list[str]]) -> dict[str, list[str]]:
    """Build reverse lookup: term -> list of concepts it belongs to."""
    reverse: dict[str, list[str]] = {}
    for concept, terms in concept_map.items():
        for term in terms:
            reverse.setdefault(term, []).append(concept)
        reverse.setdefault(concept, []).extend(terms)
    return reverse


REVERSE_MAP = build_reverse_map(CONCEPT_MAP)
