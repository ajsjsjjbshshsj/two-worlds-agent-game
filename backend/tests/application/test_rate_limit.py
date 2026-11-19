from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest


@pytest.fixture(params=["sqlite", "mongo"])
def repository_factory(request):
    return request.getfixturevalue(f"{request.param}_repository_factory")


@pytest.fixture
def setup(repository_factory, now):
    from twoworlds.application.rate_limit import SharedRateLimiter

    repo = repository_factory()
    clock = [now]
    limiter = SharedRateLimiter(repo, clock=lambda: clock[0])
    return limiter, repo, clock


def test_fixed_window_counts_and_retry_after(setup):
    from twoworlds.application.rate_limit import (
        RateLimitError,
        RateLimitPolicy,
        rate_id,
    )

    limiter, repo, clock = setup
    policy = RateLimitPolicy(3, 60)
    for _ in range(3):
        limiter.hit("key", policy)
    record = repo.get_rate_limit(rate_id("key"))
    assert record.count == 3 and record.window_start == clock[0]
    with pytest.raises(RateLimitError) as caught:
        limiter.hit("key", policy)
    assert caught.value.code == "RATE_LIMITED"
    assert caught.value.retry_after == 60
    clock[0] += timedelta(seconds=30)
    with pytest.raises(RateLimitError) as caught:
        limiter.hit("key", policy)
    assert caught.value.retry_after == 30
    # A new window starts at the first hit after expiry, not at a grid boundary.
    clock[0] += timedelta(seconds=30)
    limiter.hit("key", policy)
    fresh = repo.get_rate_limit(rate_id("key"))
    assert fresh.count == 1 and fresh.window_start == clock[0]


def test_independent_instances_share_counters(setup, repository_factory):
    from twoworlds.application.rate_limit import (
        RateLimitError,
        RateLimitPolicy,
        SharedRateLimiter,
        rate_id,
    )

    limiter, repo, clock = setup
    policy = RateLimitPolicy(3, 60)
    other = SharedRateLimiter(repository_factory(), clock=lambda: clock[0])
    limiter.hit("shared", policy)
    limiter.hit("shared", policy)
    other.hit("shared", policy)
    assert repo.get_rate_limit(rate_id("shared")).count == 3
    with pytest.raises(RateLimitError) as caught:
        other.hit("shared", policy)
    assert caught.value.code == "RATE_LIMITED"
    with pytest.raises(RateLimitError):
        limiter.hit("shared", policy)


def test_concurrent_hits_grant_exactly_the_budget(setup, repository_factory):
    from twoworlds.application.rate_limit import (
        RateLimitError,
        RateLimitPolicy,
        SharedRateLimiter,
        rate_id,
    )

    _, repo, clock = setup
    policy = RateLimitPolicy(5, 60)
    barrier = Barrier(8)

    class FirstWriteBarrier:
        def __init__(self, underlying):
            self.underlying = underlying
            self.first = True

        def __getattr__(self, name):
            return getattr(self.underlying, name)

        def _aligned(self, method, *args):
            if self.first:
                self.first = False
                barrier.wait(timeout=15)
            return method(*args)

        def create_rate_limit(self, *args):
            return self._aligned(self.underlying.create_rate_limit, *args)

        def compare_and_swap_rate_limit(self, *args):
            return self._aligned(self.underlying.compare_and_swap_rate_limit, *args)

    limiters = [
        SharedRateLimiter(
            FirstWriteBarrier(repository_factory()), clock=lambda: clock[0]
        )
        for _ in range(8)
    ]

    def run(index):
        try:
            limiters[index].hit("race", policy)
            return "accepted"
        except RateLimitError as exc:
            return exc.code

    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(run, range(8)))
    assert results.count("accepted") == 5
    assert results.count("RATE_LIMITED") == 3
    record = repo.get_rate_limit(rate_id("race"))
    assert record.count == 5 and record.version == 4


def test_window_reset_boundary(setup):
    from twoworlds.application.rate_limit import RateLimitError, RateLimitPolicy

    limiter, _, clock = setup
    policy = RateLimitPolicy(1, 60)
    limiter.hit("edge", policy)
    clock[0] += timedelta(seconds=60) - timedelta(microseconds=1)
    with pytest.raises(RateLimitError) as caught:
        limiter.hit("edge", policy)
    assert caught.value.retry_after == 1
    clock[0] += timedelta(microseconds=1)
    limiter.hit("edge", policy)


def test_capacity_fails_closed_for_new_keys_only(setup):
    from twoworlds.application.rate_limit import (
        RateLimitError,
        RateLimitPolicy,
        SharedRateLimiter,
    )

    limiter, repo, clock = setup
    limiter = SharedRateLimiter(repo, clock=lambda: clock[0], max_keys=2)
    policy = RateLimitPolicy(5, 60)
    limiter.hit("a", policy)
    limiter.hit("b", policy)
    with pytest.raises(RateLimitError) as caught:
        limiter.hit("c", policy)
    assert caught.value.code == "RATE_LIMITED"
    assert caught.value.retry_after == policy.window
    # Existing keys keep their budget; only brand-new keys are refused.
    limiter.hit("a", policy)
    clock[0] += timedelta(seconds=61)
    limiter.hit("c", policy)


def test_cleanup_deletes_only_expired(setup):
    from twoworlds.application.rate_limit import RateLimitPolicy, rate_id

    limiter, repo, clock = setup
    limiter.hit("short", RateLimitPolicy(5, 60))
    clock[0] += timedelta(seconds=30)
    limiter.hit("long", RateLimitPolicy(5, 3600))
    clock[0] += timedelta(seconds=31)
    assert limiter.cleanup(clock[0]) == 1
    assert repo.get_rate_limit(rate_id("short")) is None
    assert repo.get_rate_limit(rate_id("long")) is not None


def test_stored_record_contains_only_digested_key(setup):
    from twoworlds.application.rate_limit import RateLimitPolicy, rate_id

    limiter, repo, _ = setup
    key = "code:email:min:deadbeef"
    limiter.hit(key, RateLimitPolicy(5, 60))
    record = repo.get_rate_limit(rate_id(key))
    assert record.id == rate_id(key)
    assert key not in record.model_dump_json()


@pytest.mark.parametrize(
    "limit,window", [(0, 60), (1, 0), (-1, 60), (1.5, 60), ("3", 60), (3, 60.0)]
)
def test_policy_validation(limit, window):
    from twoworlds.application.rate_limit import RateLimitPolicy

    with pytest.raises(ValueError):
        RateLimitPolicy(limit, window)


def test_constructor_validation(repository_factory):
    from twoworlds.application.rate_limit import SharedRateLimiter

    repo = repository_factory()
    with pytest.raises(ValueError):
        SharedRateLimiter(repo, max_attempts=0)
    with pytest.raises(ValueError):
        SharedRateLimiter(repo, max_keys=0)


def test_retry_exhaustion(setup):
    from twoworlds.application.rate_limit import (
        RateLimitError,
        RateLimitPolicy,
        SharedRateLimiter,
    )

    limiter, repo, clock = setup
    policy = RateLimitPolicy(5, 60)
    limiter.hit("contested", policy)

    class NeverAccept:
        attempts = 0

        def __getattr__(self, name):
            return getattr(repo, name)

        def compare_and_swap_rate_limit(self, *args):
            self.attempts += 1
            return False

    wrapped = NeverAccept()
    contested = SharedRateLimiter(wrapped, clock=lambda: clock[0], max_attempts=3)
    with pytest.raises(RateLimitError) as caught:
        contested.hit("contested", policy)
    assert caught.value.code == "CONCURRENT_UPDATE" and wrapped.attempts == 3


def test_dependency_clock_and_key_errors(setup):
    from twoworlds.application.rate_limit import RateLimitError, RateLimitPolicy

    limiter, repo, clock = setup
    policy = RateLimitPolicy(5, 60)
    limiter.hit("live", policy)
    clock[0] -= timedelta(seconds=1)
    with pytest.raises(RateLimitError) as caught:
        limiter.hit("live", policy)
    assert caught.value.code == "CLOCK_ERROR"
    clock[0] += timedelta(seconds=1)
    for key in ("", None, 123):
        with pytest.raises(RateLimitError) as caught:
            limiter.hit(key, policy)
        assert caught.value.code == "DEPENDENCY_UNAVAILABLE"
    repo.close()
    with pytest.raises(RateLimitError) as caught:
        limiter.hit("live", policy)
    assert caught.value.code == "DEPENDENCY_UNAVAILABLE"
