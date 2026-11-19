"""Shared fixed-window rate counters persisted through the Repository CAS port.

Every application instance reads and writes the same counters, so multiple
processes cannot each grant a private budget. Keys arrive already digested by
the caller; no plaintext email or credential is stored here.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import wraps
from hashlib import sha256
from math import ceil
from typing import Callable

from pydantic import TypeAdapter

from twoworlds.domain.persistence import RateLimitRecord, UTCDateTime
from twoworlds.ports.repository import DuplicateRecord, Repository, RepositoryError

_TIME = TypeAdapter(UTCDateTime)


class RateLimitError(RuntimeError):
    def __init__(self, code: str, retry_after: int | None = None):
        self.code = code
        self.retry_after = retry_after
        super().__init__(
            {
                "RATE_LIMITED": "请求过于频繁，请稍后重试。",
                "CONCURRENT_UPDATE": "限频更新竞争，请重试。",
                "DEPENDENCY_UNAVAILABLE": "限频服务暂不可用。",
                "CLOCK_ERROR": "限频服务时间无效。",
            }[code]
        )


@dataclass(frozen=True)
class RateLimitPolicy:
    limit: int
    window: int

    def __post_init__(self):
        if type(self.limit) is not int or self.limit < 1:
            raise ValueError("Rate limit must be a positive integer")
        if type(self.window) is not int or self.window < 1:
            raise ValueError("Rate window must be a positive integer of seconds")


def _storage_errors(method):
    @wraps(method)
    def wrapped(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except RepositoryError:
            raise RateLimitError("DEPENDENCY_UNAVAILABLE") from None

    return wrapped


def rate_id(key: str) -> str:
    return "rate_" + sha256(f"tw-rate:{key}".encode("utf-8")).hexdigest()[:59]


class SharedRateLimiter:
    def __init__(
        self,
        repository: Repository,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        max_attempts: int = 8,
        max_keys: int = 10000,
    ):
        if type(max_attempts) is not int or not 1 <= max_attempts <= 32:
            raise ValueError("max_attempts must be between 1 and 32")
        if type(max_keys) is not int or max_keys < 1:
            raise ValueError("max_keys must be a positive integer")
        self._repository = repository
        self._clock = clock
        self._attempts = max_attempts
        self._capacity = max_keys

    def _now(self):
        try:
            return _TIME.validate_python(self._clock())
        except Exception:
            raise RateLimitError("CLOCK_ERROR") from None

    @_storage_errors
    def hit(self, key: str, policy: RateLimitPolicy) -> None:
        if type(key) is not str or not key:
            raise RateLimitError("DEPENDENCY_UNAVAILABLE")
        identifier = rate_id(key)
        window = timedelta(seconds=policy.window)
        for _ in range(self._attempts):
            now = self._now()
            current = self._repository.get_rate_limit(identifier)
            if current is None:
                if self._repository.count_rate_limits() >= self._capacity:
                    self._repository.delete_expired_rate_limits(now)
                    if self._repository.count_rate_limits() >= self._capacity:
                        # Fail closed for brand-new keys when the table is full.
                        raise RateLimitError("RATE_LIMITED", policy.window)
                try:
                    self._repository.create_rate_limit(
                        RateLimitRecord(
                            id=identifier,
                            count=1,
                            window_start=now,
                            expires_at=now + window,
                            version=0,
                            updated_at=now,
                        )
                    )
                except DuplicateRecord:
                    continue
                return
            if now < current.updated_at:
                raise RateLimitError("CLOCK_ERROR")
            if now >= current.expires_at:
                candidate = RateLimitRecord.model_validate(
                    current.model_dump()
                    | {
                        "count": 1,
                        "window_start": now,
                        "expires_at": now + window,
                        "version": current.version + 1,
                        "updated_at": now,
                    }
                )
            elif current.count >= policy.limit:
                remaining = (current.expires_at - now).total_seconds()
                raise RateLimitError("RATE_LIMITED", max(1, ceil(remaining)))
            else:
                candidate = RateLimitRecord.model_validate(
                    current.model_dump()
                    | {
                        "count": current.count + 1,
                        "version": current.version + 1,
                        "updated_at": now,
                    }
                )
            if self._repository.compare_and_swap_rate_limit(
                identifier, current.version, candidate
            ):
                return
        raise RateLimitError("CONCURRENT_UPDATE")

    @_storage_errors
    def cleanup(self, now: datetime) -> int:
        return self._repository.delete_expired_rate_limits(_TIME.validate_python(now))
