from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest


@pytest.fixture(params=["sqlite", "mongo"])
def repository_factory(request):
    return request.getfixturevalue(f"{request.param}_repository_factory")


@pytest.fixture
def setup(repository_factory, now):
    from twoworlds.application.identity import IdentityService

    repo = repository_factory()
    clock = [now]
    service = IdentityService(repo, clock=lambda: clock[0])
    return service, repo, clock


def test_create_and_digest_only_storage(setup, caplog):
    from twoworlds.security.credentials import digest_secret

    service, repo, clock = setup
    result = service.create_account("旅人")
    second = service.create_account("旅人")
    assert result.account.id != second.account.id
    assert result.token != result.recovery_key
    stored = repo.get_account(result.account.id)
    raw = stored.model_dump_json()
    assert stored.recovery_digest == digest_secret(result.recovery_key)
    assert stored.sessions[0].token_digest == digest_secret(result.token)
    assert result.expires_at == clock[0] + timedelta(days=7)
    assert result.token not in raw + repr(result) + caplog.text
    assert result.recovery_key not in raw + repr(result) + caplog.text
    assert service.authenticate(result.token) == stored


@pytest.mark.parametrize("credential", ["wrong", "", None, "x" * 10000])
def test_invalid_credentials_are_generic(setup, credential):
    from twoworlds.application.identity import IdentityError

    service, _, _ = setup
    for method in (service.recover, service.authenticate, service.revoke):
        with pytest.raises(IdentityError) as caught:
            method(credential)
        assert caught.value.code == "UNAUTHENTICATED"
        assert not credential or credential not in str(caught.value)


def test_recovery_wrong_kind_and_unknown_secrets(setup):
    from twoworlds.application.identity import IdentityError
    from twoworlds.security.credentials import new_secret

    service, _, _ = setup
    created = service.create_account("旅人")
    for method, secret in (
        (service.authenticate, created.account.id),
        (service.authenticate, created.recovery_key),
        (service.recover, created.token),
        (service.recover, new_secret("recovery")),
        (service.authenticate, new_secret("session")),
    ):
        with pytest.raises(IdentityError) as caught:
            method(secret)
        assert caught.value.code == "UNAUTHENTICATED"
        assert secret not in repr(caught.value)


def test_recover_and_revoke_preserve_other_sessions(setup):
    from twoworlds.application.identity import IdentityError

    service, repo, _ = setup
    created = service.create_account("旅人")
    restored = service.recover(created.recovery_key)
    assert restored.account == created.account and restored.token != created.token
    assert not hasattr(restored, "recovery_key")
    assert service.authenticate(created.token).id == restored.account.id
    service.revoke(created.token)
    stored = repo.get_account(created.account.id)
    with pytest.raises(IdentityError):
        service.authenticate(created.token)
    with pytest.raises(IdentityError):
        service.revoke(created.token)
    assert repo.get_account(created.account.id) == stored
    assert service.authenticate(restored.token).id == created.account.id


def test_expiry_boundaries(setup):
    from twoworlds.application.identity import IdentityError

    service, _, clock = setup
    created = service.create_account("旅人")
    start = clock[0]
    clock[0] = start - timedelta(microseconds=1)
    with pytest.raises(IdentityError):
        service.authenticate(created.token)
    clock[0] = start
    assert service.authenticate(created.token)
    clock[0] = created.expires_at - timedelta(microseconds=1)
    assert service.authenticate(created.token)
    clock[0] = created.expires_at
    with pytest.raises(IdentityError):
        service.authenticate(created.token)
    restored = service.recover(created.recovery_key)
    assert len(service.authenticate(restored.token).sessions) == 1


def test_latest_five_by_time_and_stable_ties(setup):
    from twoworlds.application.identity import IdentityError

    service, repo, clock = setup
    created = service.create_account("旅人")
    tokens = [created.token]
    for _ in range(4):
        clock[0] += timedelta(seconds=1)
        tokens.append(service.recover(created.recovery_key).token)
    assert all(service.authenticate(t) for t in tokens)
    # Reorder persisted sessions: eviction must use time, not tuple position.
    account = repo.get_account(created.account.id)
    assert repo.compare_and_swap_account(
        account.id,
        account.version,
        account.model_copy(
            update={
                "sessions": tuple(reversed(account.sessions)),
                "version": account.version + 1,
            }
        ),
    )
    tokens.append(service.recover(created.recovery_key).token)
    with pytest.raises(IdentityError):
        service.authenticate(tokens[0])
    assert all(service.authenticate(t) for t in tokens[1:])
    assert len(repo.get_account(account.id).sessions) == 5


def test_recovery_preserves_pair_and_save(setup, pair_record, save_record):
    service, repo, _ = setup
    created = service.create_account("旅人")
    pair = pair_record.model_copy(update={"member_a": created.account.id})
    repo.create_pair(pair)
    repo.create_save(save_record)
    assert service.recover(created.recovery_key).account.id == created.account.id
    assert repo.get_pair(pair.id) == pair
    assert repo.get_save(save_record.id) == save_record


@pytest.mark.parametrize("shared_repository", [False, True])
@pytest.mark.parametrize("operation", ["recover", "revoke", "mixed"])
def test_independent_services_real_cas_competition(
    setup, repository_factory, operation, shared_repository
):
    from twoworlds.application.identity import IdentityService

    service, repo, clock = setup
    created = service.create_account("旅人")
    extra = service.recover(created.recovery_key)
    barrier = Barrier(2)
    collisions = []

    class FirstCASBarrier:
        def __init__(self, underlying):
            self.underlying = underlying
            self.first = True

        def __getattr__(self, name):
            return getattr(self.underlying, name)

        def compare_and_swap_account(self, *args):
            if self.first:
                self.first = False
                barrier.wait(timeout=10)
            accepted = self.underlying.compare_and_swap_account(*args)
            if not accepted:
                collisions.append(False)
            return accepted

    services = [
        IdentityService(
            FirstCASBarrier(repo if shared_repository else repository_factory()),
            clock=lambda: clock[0],
        )
        for _ in range(2)
    ]

    def run(index):
        if operation == "recover" or (operation == "mixed" and index == 0):
            return services[index].recover(created.recovery_key)
        return services[index].revoke([created.token, extra.token][index])

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(run, (0, 1)))
    assert collisions
    account = repo.get_account(created.account.id)
    assert account.version == 3
    assert len(account.sessions) == {"recover": 4, "revoke": 0, "mixed": 2}[operation]
    for result in results:
        if result is not None:
            assert service.authenticate(result.token).id == account.id


def test_retry_exhaustion_does_not_return_credentials(setup):
    from twoworlds.application.identity import IdentityService, IdentityError

    service, repo, clock = setup
    created = service.create_account("旅人")
    before = repo.get_account(created.account.id)

    class NeverAccept:
        attempts = 0

        def __getattr__(self, name):
            return getattr(repo, name)

        def compare_and_swap_account(self, *args):
            self.attempts += 1
            return False

    wrapped = NeverAccept()
    contested = IdentityService(wrapped, clock=lambda: clock[0], max_attempts=3)
    with pytest.raises(IdentityError) as caught:
        contested.recover(created.recovery_key)
    assert caught.value.code == "CONCURRENT_UPDATE" and wrapped.attempts == 3
    assert repo.get_account(created.account.id) == before


def test_dependency_and_input_errors_do_not_leak(setup, caplog):
    from twoworlds.application.identity import IdentityError

    service, repo, _ = setup
    created = service.create_account("旅人")
    with pytest.raises(IdentityError) as caught:
        service.create_account(created.token * 10)
    assert created.token not in str(caught.value)
    repo.close()
    with pytest.raises(IdentityError) as caught:
        service.authenticate(created.token)
    assert caught.value.code == "DEPENDENCY_UNAVAILABLE"
    assert created.token not in str(caught.value) + caplog.text


def test_equal_time_eviction_and_generation_failure(setup):
    from twoworlds.application.identity import IdentityError, IdentityService

    service, repo, clock = setup
    created = service.create_account("旅人")
    tokens = [created.token] + [
        service.recover(created.recovery_key).token for _ in range(5)
    ]
    with pytest.raises(IdentityError):
        service.authenticate(tokens[0])
    assert all(service.authenticate(t) for t in tokens[1:])
    broken = IdentityService(
        repo, clock=lambda: clock[0], credential_generator=lambda: "weak"
    )
    before = repo.get_account(created.account.id)
    with pytest.raises(IdentityError) as caught:
        broken.recover(created.recovery_key)
    assert caught.value.code == "GENERATION_FAILED"
    assert repo.get_account(created.account.id) == before


def test_clock_rejection_and_revoke_retry_bound(setup):
    from twoworlds.application.identity import IdentityService, IdentityError

    service, repo, clock = setup
    created = service.create_account("旅人")
    clock[0] -= timedelta(seconds=1)
    with pytest.raises(IdentityError) as caught:
        service.recover(created.recovery_key)
    assert caught.value.code == "CLOCK_ERROR"
    clock[0] += timedelta(seconds=1)

    class Contested:
        attempts = 0

        def __getattr__(self, name):
            return getattr(repo, name)

        def compare_and_swap_account(self, *args):
            self.attempts += 1
            return False

    contested = Contested()
    other = IdentityService(contested, clock=lambda: clock[0], max_attempts=2)
    with pytest.raises(IdentityError) as caught:
        other.revoke(created.token)
    assert caught.value.code == "CONCURRENT_UPDATE" and contested.attempts == 2
    assert service.authenticate(created.token).version == 0


@pytest.mark.parametrize("operation", ["authenticate", "revoke"])
def test_authentication_rejects_clock_before_persisted_update(setup, operation):
    from twoworlds.application.identity import IdentityError

    service, repo, clock = setup
    created = service.create_account("旅人")
    start = clock[0]
    clock[0] = start + timedelta(hours=1)
    service.recover(created.recovery_key)
    current = repo.get_account(created.account.id)
    assert current.updated_at == clock[0]
    clock[0] = start + timedelta(minutes=30)
    assert start <= clock[0] < created.expires_at
    with pytest.raises(IdentityError) as caught:
        getattr(service, operation)(created.token)
    assert caught.value.code == "CLOCK_ERROR"
    assert repo.get_account(created.account.id) == current
    # The persisted boundary itself is valid; this is not a global clock monitor.
    clock[0] = current.updated_at
    assert service.authenticate(created.token) == current
