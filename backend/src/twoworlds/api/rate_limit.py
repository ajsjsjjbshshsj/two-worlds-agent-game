"""Bounded per-application fixed windows. No credential material is used as a key."""

from collections import OrderedDict
from math import ceil, isfinite
from threading import Lock
import time


class RateLimiter:
    def __init__(self, *, limit=5, window=60, max_keys=10000, clock=time.monotonic):
        if (
            type(limit) is not int
            or limit < 1
            or type(max_keys) is not int
            or max_keys < 1
        ):
            raise ValueError("Rate limits and capacity must be positive integers")
        if not isinstance(window, (int, float)) or not isfinite(window) or window <= 0:
            raise ValueError("Window must be positive and finite")
        self._limit, self._window, self._capacity = limit, window, max_keys
        self._clock = clock
        self._buckets = OrderedDict()
        self._lock = Lock()
        self._last = float("-inf")

    @property
    def size(self):
        with self._lock:
            return len(self._buckets)

    def check(self, route, client):
        with self._lock:
            value = float(self._clock())
            if not isfinite(value):
                raise ValueError("Invalid limiter clock")
            now = max(value, self._last)
            self._last = now
            # Insertion order is window-start order; hits never reorder buckets.
            while self._buckets:
                start, _ = next(iter(self._buckets.values()))
                if now - start < self._window:
                    break
                self._buckets.popitem(last=False)
            key = (route, client)
            if key not in self._buckets:
                if len(self._buckets) >= self._capacity:
                    start, _ = next(iter(self._buckets.values()))
                    return max(1, ceil(start + self._window - now))
                self._buckets[key] = (now, 1)
                return None
            start, count = self._buckets[key]
            if count >= self._limit:
                return max(1, ceil(start + self._window - now))
            self._buckets[key] = (start, count + 1)
            return None
