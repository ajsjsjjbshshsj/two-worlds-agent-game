from datetime import timedelta

import pytest

from twoworlds.domain.engine import create_initial_state


@pytest.fixture(params=["sqlite", "mongo"])
def save_repository_factory(request):
    return request.getfixturevalue(f"{request.param}_repository_factory")


@pytest.fixture
def saves(save_repository_factory, account_factory, pair_record, published_story, now):
    from twoworlds.application.saves import SaveService

    repo = save_repository_factory()
    for role in ("a", "b", "c"):
        repo.create_account(account_factory(role))
    repo.create_pair(pair_record)
    store, publish = published_story
    script = publish()
    clock = [now]
    return (
        SaveService(repo, store, clock=lambda: clock[0]),
        repo,
        script,
        publish,
        clock,
    )


def test_initial_creation_repeat_read_and_unfilled_pair(saves):
    service, repo, script, _, clock = saves
    view = service.create_save("account_a", "pair_one", "lighthouse", "1.0.0")
    stored = repo.get_save(view.id)
    assert stored.state == create_initial_state(script)
    assert stored.version == stored.public_history.through_version == 0
    assert stored.receipts == stored.dialogues == ()
    assert stored.created_at == stored.updated_at == clock[0]
    assert service.read_save("account_a", view.id) == view
    assert service.create_save("account_a", "pair_one", "lighthouse", "1.0.0") == view
    assert len(service.list_saves("account_a")) == 1
    assert service.list_saves("account_b") == ()


@pytest.mark.parametrize("operation", ["create", "read", "list"])
def test_outsider_and_missing_are_hidden(saves, operation):
    from twoworlds.application.saves import SaveError

    service, _, _, _, _ = saves
    view = service.create_save("account_a", "pair_one", "lighthouse", "1.0.0")
    with pytest.raises(SaveError) as error:
        if operation == "create":
            service.create_save("account_c", "pair_one", "lighthouse", "1.0.0")
        elif operation == "read":
            service.read_save("account_c", view.id)
        else:
            service.list_saves("account_c", "pair_one")
    assert error.value.code == "SAVE_NOT_FOUND"
    with pytest.raises(SaveError) as error:
        service.read_save("account_a", "missing")
    assert error.value.code == "SAVE_NOT_FOUND"


def test_member_join_and_distinct_personal_snapshots(saves):
    service, repo, _, _, clock = saves
    view = service.create_save("account_a", "pair_one", "lighthouse", "1.0.0")
    pair = repo.get_pair("pair_one")
    repo.join_pair(pair.id, "account_b", pair.invite_digest, clock[0])
    a, b = (service.read_save("account_" + r, view.id) for r in ("a", "b"))
    assert a.role == "a" and b.role == "b"
    assert a.personal.devices != b.personal.devices
    assert a.personal.observations != b.personal.observations
    assert a.public == b.public
    assert service.list_saves("account_b")[0].id == view.id


def test_pinned_versions_and_unpublished_rejected(saves):
    from twoworlds.application.saves import SaveError

    service, repo, _, publish, _ = saves
    for version in ("9.0.0", "2.0.0"):
        with pytest.raises(SaveError) as error:
            service.create_save("account_a", "pair_one", "lighthouse", version)
        assert error.value.code == "SCRIPT_NOT_FOUND"
    view = service.create_save("account_a", "pair_one", "lighthouse", "1.0.0")
    publish(version="2.0.0")
    with pytest.raises(SaveError) as error:
        service.create_save("account_a", "pair_one", "lighthouse", "2.0.0")
    assert error.value.code == "SCRIPT_VERSION_CONFLICT"
    assert service.read_save("account_a", view.id).script_version == "1.0.0"
    assert repo.get_save(view.id).version == 0


def test_clock_rollback_does_not_create_save(saves):
    from twoworlds.application.saves import SaveError

    service, repo, _, _, clock = saves
    clock[0] -= timedelta(seconds=1)
    with pytest.raises(SaveError) as error:
        service.create_save("account_a", "pair_one", "lighthouse", "1.0.0")
    assert error.value.code == "CLOCK_ERROR"
    assert repo.get_save_for_pair_script("pair_one", "lighthouse") is None
