"""Caching (Phase 24).

Three caches, each safe by construction:

  - **embeddings** — text → vector is deterministic, so identical text always
    embeds to the same thing. An LRU cache means query variants (Phase 21) and
    repeated questions skip the embed API entirely. No TTL needed; it's never
    stale. Global (embeddings don't depend on the user).

  - **retrieval** — (user, mode, k, query) → hits, with a short TTL *and* a
    per-user version stamped into the key. Any document write bumps that version
    (see db.py), so a cached result can never outlive the data it came from.

  - **responses** — (user, k, messages) → the grounded RAG answer, short TTL +
    version. Safe because the whole input (the full message list) is in the key,
    so we only reuse a response for a byte-identical request.

Everything is in-memory (a single process on the free tier) and thread-safe. We
also track hit/miss counts so the win is observable (GET /cache/stats).
"""

import hashlib
import threading
import time
from collections import OrderedDict


def content_hash(*parts) -> str:
    """A stable key from arbitrary parts (order-sensitive, null-separated)."""
    h = hashlib.sha256()
    for part in parts:
        h.update(str(part).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


class _Stats:
    def __init__(self) -> None:
        self.hits = 0
        self.misses = 0

    def as_dict(self, size: int) -> dict:
        total = self.hits + self.misses
        return {
            "hits": self.hits,
            "misses": self.misses,
            "size": size,
            "hit_rate": round(self.hits / total, 3) if total else None,
        }


class LRUCache:
    """Fixed-capacity least-recently-used cache."""

    def __init__(self, capacity: int = 4096) -> None:
        self.capacity = capacity
        self._data: OrderedDict[str, object] = OrderedDict()
        self._lock = threading.Lock()
        self.stats = _Stats()

    def get(self, key: str):
        with self._lock:
            if key in self._data:
                self._data.move_to_end(key)
                self.stats.hits += 1
                return self._data[key]
            self.stats.misses += 1
            return None

    def set(self, key: str, value) -> None:
        with self._lock:
            self._data[key] = value
            self._data.move_to_end(key)
            while len(self._data) > self.capacity:
                self._data.popitem(last=False)  # evict oldest

    def as_dict(self) -> dict:
        return self.stats.as_dict(len(self._data))


class TTLCache:
    """Time-bounded cache: entries expire after `ttl` seconds."""

    def __init__(self, ttl: float = 60.0, capacity: int = 512) -> None:
        self.ttl = ttl
        self.capacity = capacity
        self._data: OrderedDict[str, tuple[float, object]] = OrderedDict()
        self._lock = threading.Lock()
        self.stats = _Stats()

    def get(self, key: str):
        with self._lock:
            entry = self._data.get(key)
            if entry is not None:
                expiry, value = entry
                if expiry > time.time():
                    self.stats.hits += 1
                    self._data.move_to_end(key)
                    return value
                del self._data[key]  # expired
            self.stats.misses += 1
            return None

    def set(self, key: str, value) -> None:
        with self._lock:
            self._data[key] = (time.time() + self.ttl, value)
            self._data.move_to_end(key)
            while len(self._data) > self.capacity:
                self._data.popitem(last=False)

    def as_dict(self) -> dict:
        return self.stats.as_dict(len(self._data))


# --- The module-level caches -------------------------------------------------
embeddings = LRUCache(capacity=4096)
retrieval = TTLCache(ttl=60.0, capacity=512)
responses = TTLCache(ttl=120.0, capacity=256)


# --- Per-user document version (retrieval/response invalidation) --------------
_versions: dict[int, int] = {}
_ver_lock = threading.Lock()


def user_version(user_id: int) -> int:
    with _ver_lock:
        return _versions.get(user_id, 0)


def bump_user_version(user_id: int) -> None:
    """Invalidate a user's cached retrievals/responses after a document write."""
    with _ver_lock:
        _versions[user_id] = _versions.get(user_id, 0) + 1


def stats() -> dict:
    return {
        "embeddings": embeddings.as_dict(),
        "retrieval": retrieval.as_dict(),
        "responses": responses.as_dict(),
    }
