from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest

from tests.identity_support import PASSWORD, unique_email


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


def test_register_stores_digests_only(setup, caplog):
    from twoworlds.security.credentials import digest_secret
    from twoworlds.security.passwords import verify_password

    service, repo, clock = setup
    email = unique_email()
    result = service.register(email, PASSWORD, "旅人")
    stored = repo.get_account(result.account.id)
    assert stored.email == email
    assert stored.email_verified_at == clock[0]
    assert verify_password(stored.password_hash, PASSWORD)
    assert stored.sessions[0].token_digest == digest_secret(result.token)
    assert result.expires_at == clock[0] + timedelta(days=7)
    blob = stored.model_dump_json() + repr(result) + caplog.text
    assert PASSWORD not in blob
    assert result.token not in blob
    assert not hasattr(result, "recovery_key")
    assert result.account.email == email
    assert result.account.display_name == "旅人"
    assert service.authenticate(result.token) == stored


def test_register_duplicate_email_including_case_variants(setup):
    from twoworlds.application.identity import IdentityError

    service, repo, _ = setup
    email = unique_email()
    service.register(email, PASSWORD, "旅人")
    for variant in (email, email.upper(), "  " + email + "  "):
        with pytest.raises(IdentityError) as caught:
            service.register(variant, PASSWORD, "别人")
        assert caught.value.code == "EMAIL_ALREADY_REGISTERED"
    assert repo.get_account_by_email(email).display_name == "旅人"


def test_concurrent_registration_keeps_single_account(setup, repository_factory):
    from twoworlds.application.identity import IdentityError, IdentityService

    _, repo, clock = setup
    email = unique_email()
    barrier = Barrier(2)

    class RegistrationBarrier:
        """让两个注册都先通过存在性检查，再同时插入，逼出真实唯一约束竞争。"""

        def __init__(self, underlying):
            self.underlying = underlying
            self.first = True

        def __getattr__(self, name):
            return getattr(self.underlying, name)

        def create_account(self, account):
            if self.first:
                self.first = False
                barrier.wait(timeout=10)
            return self.underlying.create_account(account)

    services = [
        IdentityService(
            RegistrationBarrier(repository_factory()), clock=lambda: clock[0]
        )
        for _ in range(2)
    ]

    def run(index):
        try:
            return services[index].register(email, PASSWORD, f"旅人{index}")
        except IdentityError as error:
            assert error.code == "EMAIL_ALREADY_REGISTERED"
            return None

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(run, (0, 1)))
    winners = [result for result in results if result is not None]
    assert len(winners) == 1
    stored = repo.get_account_by_email(email)
    assert stored.version == 0
    assert stored.display_name == winners[0].account.display_name
    assert repo.get_account(winners[0].account.id) == stored


def test_register_invalid_input_creates_nothing(setup):
    from twoworlds.application.identity import IdentityError

    service, repo, _ = setup
    cases = [
        ("not-an-email", PASSWORD, "旅人"),
        (unique_email(), "short", "旅人"),
        (unique_email(), "x" * 129, "旅人"),
        (unique_email(), PASSWORD, ""),
        (unique_email(), PASSWORD, "名" * 41),
    ]
    for email, password, name in cases:
        with pytest.raises(IdentityError) as caught:
            service.register(email, password, name)
        assert caught.value.code == "INVALID_INPUT"
        assert repo.get_account_by_email(email) is None


def test_login_issues_new_session_and_rejects_wrong_credentials(setup):
    from twoworlds.application.identity import IdentityError

    service, _, _ = setup
    email = unique_email()
    created = service.register(email, PASSWORD, "旅人")
    logged = service.login(email, PASSWORD)
    assert logged.account == created.account
    assert logged.token != created.token
    assert service.authenticate(logged.token).id == created.account.id
    assert service.authenticate(created.token).id == created.account.id
    for password in (PASSWORD + "!", "wrong password 1", "", "x" * 129, None, 12345):
        with pytest.raises(IdentityError) as caught:
            service.login(email, password)
        assert caught.value.code == "INVALID_CREDENTIALS"
        assert (
            not isinstance(password, str)
            or not password
            or (password not in str(caught.value))
        )
    with pytest.raises(IdentityError) as caught:
        service.login(unique_email(), PASSWORD)
    assert caught.value.code == "INVALID_CREDENTIALS"


def test_unknown_email_and_malformed_password_use_dummy_verify(setup, monkeypatch):
    import twoworlds.application.identity as identity_module
    from twoworlds.application.identity import IdentityError

    service, _, _ = setup
    email = unique_email()
    service.register(email, PASSWORD, "旅人")
    calls = []
    monkeypatch.setattr(
        identity_module, "dummy_verify", lambda value: calls.append(value)
    )
    with pytest.raises(IdentityError):
        service.login(unique_email(), PASSWORD)
    with pytest.raises(IdentityError):
        service.login(email, "short")
    # Unknown accounts and malformed passwords take the same-cost dummy path,
    # so response timing does not reveal whether the email exists.
    assert len(calls) == 2
    with pytest.raises(IdentityError):
        service.login(email, PASSWORD + "!")
    assert len(calls) == 2


def test_login_upgrades_weak_hash(setup):
    from argon2 import PasswordHasher, Type

    from twoworlds.security.passwords import needs_rehash, verify_password

    service, repo, _ = setup
    email = unique_email()
    created = service.register(email, PASSWORD, "旅人")
    weak = PasswordHasher(
        time_cost=1, memory_cost=8192, parallelism=1, type=Type.ID
    ).hash(PASSWORD)
    account = repo.get_account(created.account.id)
    assert repo.compare_and_swap_account(
        account.id,
        account.version,
        account.model_copy(
            update={"password_hash": weak, "version": account.version + 1}
        ),
    )
    assert needs_rehash(weak)
    logged = service.login(email, PASSWORD)
    stored = repo.get_account(created.account.id)
    assert stored.password_hash != weak
    assert not needs_rehash(stored.password_hash)
    assert verify_password(stored.password_hash, PASSWORD)
    assert service.authenticate(logged.token).id == created.account.id


def test_reset_password_revokes_all_sessions(setup):
    from twoworlds.application.identity import IdentityError

    service, _, _ = setup
    email = unique_email()
    created = service.register(email, PASSWORD, "旅人")
    extra = service.login(email, PASSWORD)
    service.reset_password(email, "new password 77")
    for token in (created.token, extra.token):
        with pytest.raises(IdentityError) as caught:
            service.authenticate(token)
        assert caught.value.code == "UNAUTHENTICATED"
    with pytest.raises(IdentityError):
        service.login(email, PASSWORD)
    fresh = service.login(email, "new password 77")
    assert fresh.account.id == created.account.id
    with pytest.raises(IdentityError) as caught:
        service.reset_password(unique_email(), "new password 77")
    assert caught.value.code == "INVALID_INPUT"


@pytest.mark.parametrize("credential", ["wrong", "", None, "x" * 10000])
def test_invalid_session_credentials_are_generic(setup, credential):
    from twoworlds.application.identity import IdentityError

    service, _, _ = setup
    for method in (service.authenticate, service.revoke):
        with pytest.raises(IdentityError) as caught:
            method(credential)
        assert caught.value.code == "UNAUTHENTICATED"
        assert not credential or credential not in str(caught.value)


def test_wrong_credential_namespaces_are_rejected(setup):
    from twoworlds.application.identity import IdentityError
    from twoworlds.security.credentials import new_secret

    service, _, _ = setup
    created = service.register(unique_email(), PASSWORD, "旅人")
    for secret in (created.account.id, new_secret("invite"), "wrong"):
        with pytest.raises(IdentityError) as caught:
            service.authenticate(secret)
        assert caught.value.code == "UNAUTHENTICATED"
        assert secret not in repr(caught.value)


def test_expiry_boundaries(setup):
    from twoworlds.application.identity import IdentityError

    service, _, clock = setup
    email = unique_email()
    created = service.register(email, PASSWORD, "旅人")
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
    logged = service.login(email, PASSWORD)
    assert len(service.authenticate(logged.token).sessions) == 1


def test_latest_five_by_time_and_stable_ties(setup):
    from twoworlds.application.identity import IdentityError

    service, repo, clock = setup
    email = unique_email()
    created = service.register(email, PASSWORD, "旅人")
    tokens = [created.token]
    for _ in range(4):
        clock[0] += timedelta(seconds=1)
        tokens.append(service.login(email, PASSWORD).token)
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
    tokens.append(service.login(email, PASSWORD).token)
    with pytest.raises(IdentityError):
        service.authenticate(tokens[0])
    assert all(service.authenticate(t) for t in tokens[1:])
    assert len(repo.get_account(account.id).sessions) == 5


def test_login_preserves_pair_and_save(setup, pair_record, save_record):
    service, repo, _ = setup
    created = service.register(unique_email(), PASSWORD, "旅人")
    pair = pair_record.model_copy(update={"member_a": created.account.id})
    repo.create_pair(pair)
    repo.create_save(save_record)
    assert service.login(created.account.email, PASSWORD).account.id == (
        created.account.id
    )
    assert repo.get_pair(pair.id) == pair
    assert repo.get_save(save_record.id) == save_record


@pytest.mark.parametrize("shared_repository", [False, True])
@pytest.mark.parametrize("operation", ["login", "revoke", "mixed"])
def test_independent_services_real_cas_competition(
    setup, repository_factory, operation, shared_repository
):
    from twoworlds.application.identity import IdentityService

    service, repo, clock = setup
    email = unique_email()
    created = service.register(email, PASSWORD, "旅人")
    extra = service.login(email, PASSWORD)
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
        if operation == "login" or (operation == "mixed" and index == 0):
            return services[index].login(email, PASSWORD)
        return services[index].revoke([created.token, extra.token][index])

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(run, (0, 1)))
    assert collisions
    account = repo.get_account(created.account.id)
    assert account.version == 3
    assert len(account.sessions) == {"login": 4, "revoke": 0, "mixed": 2}[operation]
    for result in results:
        if result is not None:
            assert service.authenticate(result.token).id == account.id


def test_retry_exhaustion_does_not_return_credentials(setup):
    from twoworlds.application.identity import IdentityError, IdentityService

    service, repo, clock = setup
    email = unique_email()
    created = service.register(email, PASSWORD, "旅人")
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
        contested.login(email, PASSWORD)
    assert caught.value.code == "CONCURRENT_UPDATE" and wrapped.attempts == 3
    assert repo.get_account(created.account.id) == before


def test_dependency_and_input_errors_do_not_leak(setup, caplog):
    from twoworlds.application.identity import IdentityError

    service, repo, _ = setup
    email = unique_email()
    created = service.register(email, PASSWORD, "旅人")
    with pytest.raises(IdentityError) as caught:
        service.register(email, PASSWORD, "")
    assert caught.value.code == "INVALID_INPUT"
    assert PASSWORD not in str(caught.value)
    repo.close()
    with pytest.raises(IdentityError) as caught:
        service.authenticate(created.token)
    assert caught.value.code == "DEPENDENCY_UNAVAILABLE"
    assert created.token not in str(caught.value) + caplog.text
    assert PASSWORD not in caplog.text


def test_equal_time_eviction_and_generation_failure(setup):
    from twoworlds.application.identity import IdentityError, IdentityService

    service, repo, clock = setup
    email = unique_email()
    created = service.register(email, PASSWORD, "旅人")
    tokens = [created.token] + [service.login(email, PASSWORD).token for _ in range(5)]
    with pytest.raises(IdentityError):
        service.authenticate(tokens[0])
    assert all(service.authenticate(t) for t in tokens[1:])
    broken = IdentityService(
        repo, clock=lambda: clock[0], credential_generator=lambda: "weak"
    )
    before = repo.get_account(created.account.id)
    with pytest.raises(IdentityError) as caught:
        broken.login(email, PASSWORD)
    assert caught.value.code == "GENERATION_FAILED"
    assert repo.get_account(created.account.id) == before


def test_clock_rejection_and_revoke_retry_bound(setup):
    from twoworlds.application.identity import IdentityError, IdentityService

    service, repo, clock = setup
    email = unique_email()
    created = service.register(email, PASSWORD, "旅人")
    clock[0] -= timedelta(seconds=1)
    with pytest.raises(IdentityError) as caught:
        service.login(email, PASSWORD)
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
    email = unique_email()
    created = service.register(email, PASSWORD, "旅人")
    start = clock[0]
    clock[0] = start + timedelta(hours=1)
    service.login(email, PASSWORD)
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
