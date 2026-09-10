"""Scalar LRU observations without changing batch inference context.

source: ADR-0518"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections import OrderedDict


class _EmbeddingCacheMixin(ABC):
    _cache: OrderedDict[str, bytes]
    _cache_max: int
    _cache_hits: int
    _cache_misses: int
    _batch_reuses: int

    @staticmethod
    @abstractmethod
    def _cache_key(text: str) -> str:
        """Compute the cache key through the embedding math mixin.

        source: ADR-0518"""

    def _cache_store(self, key: str, vector: bytes) -> None:
        # source: ADR-0518
        if self._cache_max <= 0:
            return
        self._cache[key] = vector
        self._cache.move_to_end(key)
        if len(self._cache) > self._cache_max:
            self._cache.popitem(last=False)

    def cache_info(self) -> dict[str, int]:
        """Hits/misses count nonempty scalar lookups only. Batch calls do not
                interact with this cache; batch_reuses remains zero. Failed scalar
                lookups still count. Explicit warm_cache retains its existing behavior.

        source: ADR-0518"""
        return {
            "hits": self._cache_hits,
            "misses": self._cache_misses,
            "batch_reuses": self._batch_reuses,
            "size": len(self._cache),
            "capacity": self._cache_max,
        }
