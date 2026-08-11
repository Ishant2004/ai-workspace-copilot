"""In-process rate limiting (Phase 29).

A single free-tier process, so no Redis: a thread-safe fixed-window counter per
key is enough to stop one user (or IP) from hammering the LLM/DB. Each key tracks
how many requests it made in the current window; when the window elapses it
resets. Over the limit → the caller raises HTTP 429.

Fixed-window is the simplest correct-enough choice (a token bucket would smooth
bursts better, but this is plenty for abuse prevention on a small app).
"""

import threading
import time

_lock = threading.Lock()
# key -> (window_start_epoch, count)
_windows: dict[str, tuple[float, int]] = {}


def allow(key: str, limit: int, window_seconds: int) -> bool:
    """Record a request for `key`; return False if it exceeds `limit`/window."""
    now = time.time()
    with _lock:
        start, count = _windows.get(key, (now, 0))
        if now - start >= window_seconds:
            start, count = now, 0  # window elapsed → reset
        count += 1
        _windows[key] = (start, count)
        return count <= limit


def reset() -> None:
    """Clear all counters (used by tests)."""
    with _lock:
        _windows.clear()
