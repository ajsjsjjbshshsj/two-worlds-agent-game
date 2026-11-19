from datetime import datetime, timedelta, timezone
import logging

import pytest

from twoworlds.security.credentials import digest_secret, new_secret


@pytest.fixture(params=["sqlite", "mongo"])
def repository_factory(request):
    return request.getfixturevalue(f"{request.param}_repository_factory")


@pytest.fixture
def setup(repository_factory, account_factory, now):
    from twoworlds.application.pairs import PairService

    repo = repository_factory()
    for name in ("a", "b", "c"):
        repo.create_account(account_factory(name))
    clock = [now]
    return PairService(repo, clock=lambda: clock[0]), repo, clock


def expect(code, operation):
    from twoworlds.application.pairs import PairError

    with pytest.raises(PairError) as caught:
        operation()
    assert caught.value.code == code
    return caught.value


def test_create_fixed_roles_entropy_expiry_and_digest_only(setup, caplog):
    caplog.set_level(logging.INFO)
    service, repo, clock = setup
    made = service.create_pair("account_a")
    other = service.create_pair("account_a")
    assert made.id != other.id and made.invite_token != other.invite_token
    assert made.invite_token.startswith("tw_invite_")
    assert len(made.invite_token.removeprefix("tw_invite_")) == 43
    assert made.invite_expires_at == clock[0] + timedelta(hours=24)
    stored = repo.get_pair(made.id)
    assert stored.member_a == "account_a" and stored.member_b is None
    assert stored.version == 0 and stored.updated_at == clock[0]
    assert stored.invite_digest == digest_secret(made.invite_token, "invite")
    assert made.invite_token not in stored.model_dump_json() + repr(made) + caplog.text


def test_join_owner_repeat_and_third_person(setup):
    service, repo, clock = setup
    made = service.create_pair("account_a")
    before = repo.get_pair(made.id)
    expect("INVITE_INVALID", lambda: service.join_pair("account_a", made.invite_token))
    assert repo.get_pair(made.id) == before
    joined = service.join_pair("account_b", made.invite_token)
    assert joined.id == made.id and joined.role == "b"
    stored = repo.get_pair(made.id)
    assert stored.member_b == "account_b" and stored.version == 1
    clock[0] += timedelta(days=2)
    assert service.join_pair("account_b", made.invite_token) == joined
    assert repo.get_pair(made.id) == stored
    expect("PAIR_FULL", lambda: service.join_pair("account_c", made.invite_token))
    expect("PAIR_FULL", lambda: service.refresh_invite("account_a", made.id))
    expect("PAIR_NOT_FOUND", lambda: service.refresh_invite("account_b", made.id))
    assert repo.get_pair(made.id) == stored


@pytest.mark.parametrize("microseconds,accepted", [(-1, True), (0, False), (1, False)])
def test_expiry_boundary(setup, microseconds, accepted):
    service, repo, clock = setup
    made = service.create_pair("account_a")
    clock[0] = made.invite_expires_at + timedelta(microseconds=microseconds)
    if accepted:
        assert service.join_pair("account_b", made.invite_token).id == made.id
    else:
        before = repo.get_pair(made.id)
        expect(
            "INVITE_INVALID", lambda: service.join_pair("account_b", made.invite_token)
        )
        assert repo.get_pair(made.id) == before


def test_refresh_invalidates_old_invite_and_resets_expiry(setup):
    service, repo, clock = setup
    made = service.create_pair("account_a")
    expect("PAIR_NOT_FOUND", lambda: service.refresh_invite("account_b", made.id))
    expect("PAIR_NOT_FOUND", lambda: service.refresh_invite("account_a", "missing"))
    clock[0] += timedelta(hours=25)
    fresh = service.refresh_invite("account_a", made.id)
    assert fresh.invite_token != made.invite_token
    assert fresh.invite_expires_at == clock[0] + timedelta(hours=24)
    assert repo.get_pair(made.id).version == 1
    expect("INVITE_INVALID", lambda: service.join_pair("account_b", made.invite_token))
    assert service.join_pair("account_b", fresh.invite_token).id == made.id


@pytest.mark.parametrize("value", [None, "", "wrong", "x" * 10000])
def test_invalid_invite_is_generic(setup, value):
    service, _, _ = setup
    error = expect("INVITE_INVALID", lambda: service.join_pair("account_b", value))
    if value:
        assert value not in str(error)


def test_wrong_namespaces_and_unknown_invite_rejected(setup):
    service, _, _ = setup
    for value in (new_secret("session"), new_secret("invite"), "x" * 43):
        expect("INVITE_INVALID", lambda: service.join_pair("account_b", value))
    token = new_secret("invite")
    with pytest.raises(ValueError):
        digest_secret(token, "session")


def test_member_list_only_own_roles_and_stable_order(setup):
    service, _, _ = setup
    first = service.create_pair("account_a")
    second = service.create_pair("account_b")
    service.join_pair("account_a", second.invite_token)
    service.create_pair("account_c")
    own = service.list_pairs("account_a")
    assert [p.id for p in own] == sorted([first.id, second.id])
    assert {p.id: (p.role, p.member_count) for p in own} == {
        first.id: ("a", 1),
        second.id: ("b", 2),
    }


def test_unique_conflict_retries_and_same_token_refresh_is_rejected(setup):
    from twoworlds.application.pairs import PairService

    _, repo, clock = setup
    values = iter(["X" * 43, "X" * 43, "Y" * 43])
    service = PairService(
        repo, clock=lambda: clock[0], credential_generator=lambda: next(values)
    )
    first, other = service.create_pair("account_a"), service.create_pair("account_b")
    assert first.invite_token != other.invite_token
    attempts = []

    def same():
        attempts.append(1)
        return "X" * 43

    limited = PairService(
        repo, clock=lambda: clock[0], credential_generator=same, max_attempts=2
    )
    before = repo.get_pair(first.id)
    expect("GENERATION_FAILED", lambda: limited.create_pair("account_a"))
    assert len(attempts) == 2
    attempts.clear()
    expect("GENERATION_FAILED", lambda: limited.refresh_invite("account_a", first.id))
    assert len(attempts) == 2 and repo.get_pair(first.id) == before
    values = iter(["Y" * 43, "Z" * 43])
    fresh = service.refresh_invite("account_a", first.id)
    assert fresh.invite_token.endswith("Z" * 43)
    assert repo.get_pair(other.id).invite_digest == digest_secret(other.invite_token)


def test_clock_errors_and_utc_normalization(setup):
    from twoworlds.application.pairs import PairService

    service, repo, clock = setup
    clock[0] = clock[0].astimezone(timezone(timedelta(hours=8)))
    made = service.create_pair("account_a")
    assert made.invite_expires_at.utcoffset() == timedelta(0)
    before = repo.get_pair(made.id)
    clock[0] -= timedelta(seconds=1)
    expect("CLOCK_ERROR", lambda: service.refresh_invite("account_a", made.id))
    expect("CLOCK_ERROR", lambda: service.join_pair("account_b", made.invite_token))
    assert repo.get_pair(made.id) == before
    for value in (datetime(2026, 1, 1), datetime.max.replace(tzinfo=timezone.utc)):
        broken = PairService(repo, clock=lambda: value)
        expect("CLOCK_ERROR", lambda: broken.create_pair("account_a"))


def test_failure_bounds_and_dependency_sanitization(setup, caplog):
    from twoworlds.application.pairs import PairService

    service, repo, clock = setup
    made = service.create_pair("account_a")

    class NeverAccept:
        calls = 0

        def __getattr__(self, name):
            return getattr(repo, name)

        def compare_and_swap_pair(self, *args):
            self.calls += 1
            return False

    denied = NeverAccept()
    limited = PairService(denied, clock=lambda: clock[0], max_attempts=2)
    expect("CONCURRENT_UPDATE", lambda: limited.refresh_invite("account_a", made.id))
    assert denied.calls == 2
    broken = PairService(repo, credential_generator=lambda: "private-generator-failure")
    failure = expect("GENERATION_FAILED", lambda: broken.create_pair("account_a"))
    assert "private-generator-failure" not in str(failure) + caplog.text
    repo.close()
    expect("DEPENDENCY_UNAVAILABLE", lambda: service.list_pairs("account_a"))
