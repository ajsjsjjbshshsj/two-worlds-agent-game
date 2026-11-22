"""Run the real graph in HTTP commands backed by SQLite and MongoDB."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import logging
from threading import Barrier, Event

import pytest

from tests.ai.log_support import wait_for_log
from tests.ai.test_graph import FakeProvider, fake_reply
from tests.api import test_saves as lifecycle
from tests.contracts.support import Platform, command, error, ok
from tests.save_support import published_story  # noqa: F401
from tests.storage.conftest import mongo_database, mongo_repository_factory  # noqa: F401
from twoworlds.ai.graph import NarrativeLimits
from twoworlds.application.dialogue import DEMO_ANSWER
from twoworlds.application.saves import SaveService

save_apps = lifecycle.save_apps
save_repository_factory = lifecycle.save_repository_factory
sqlite_repository_factory = lifecycle.sqlite_repository_factory


@pytest.fixture
def world(save_apps):
    factory, store, _, _ = save_apps
    client, repo = factory()
    other, independent_repo = factory()
    assert independent_repo is not repo
    game = Platform(client, lambda: None)
    peer = Platform(other, lambda: None)
    a, b, pair = game.pair()
    save = game.save(a, pair)

    def install(provider, limits=NarrativeLimits(timeout_seconds=5)):
        client.app.state.save_service = SaveService(
            repo,
            store,
            clock=lambda: datetime(2026, 11, 15, tzinfo=timezone.utc),
            narrative_provider=provider,
            narrative_limits=limits,
        )

    return game, peer, a, b, save, repo, install


def talk(save, question="SECRET_PLAYER_CONTENT"):
    return command(save, "talk", {"question": question})


def blocking_provider(release, entered, output):
    def produce(request):
        entered.set()
        if not release.wait(10):
            raise AssertionError("Test did not release blocked generation")
        return output(request)

    return FakeProvider(produce)


@pytest.mark.parametrize("invalid_output", [False, True], ids=["generated", "fallback"])
def test_partner_advances_while_graph_runs_and_stale_result_never_lands(
    world, caplog, invalid_output
):
    game, peer, a, b, save, repo, install = world
    release, entered = Event(), Event()
    provider = blocking_provider(
        release,
        entered,
        lambda request: fake_reply(request, **({"text": ""} if invalid_output else {})),
    )
    install(provider)
    body = talk(save)
    with caplog.at_level(logging.INFO, logger="twoworlds.ai.graph"):
        with ThreadPoolExecutor(2) as executor:
            pending = executor.submit(game.post, a, save, body)
            try:
                assert entered.wait(5) and not pending.done()
                # This is a second app and repository connected to the same
                # real database. It must commit before the provider is released.
                advancing = executor.submit(
                    peer.accept, b, save, "inspect", {"target": "sea_chart"}
                )
                assert advancing.result(timeout=3)["version"] == 1
                committed = repo.get_save(save["id"])
                assert not pending.done()
            finally:
                release.set()
            assert not error(pending.result(timeout=5), 409, "VERSION_CONFLICT")[
                "retryable"
            ]
        wait_for_log(caplog, "disposition=stale")

    assert len(provider.calls) == 1
    assert game.receipt(a, save, body["request_id"]) == {"accepted": False}
    assert repo.get_save(save["id"]) == committed
    assert committed.dialogues == ()
    assert [r.actor_id for r in committed.receipts] == [b.account_id]
    assert committed.state.discovered_clues == ("b_sea_chart",)
    assert committed.state.version == committed.public_history.through_version == 1
    a_view, b_view = game.read(a, save), peer.read(b, save)
    assert a_view["version"] == b_view["version"] == 1
    assert a_view["personal"]["clues"] == [] and a_view["personal"]["dialogue"] == []
    assert [c["id"] for c in b_view["personal"]["clues"]] == ["b_sea_chart"]
    assert "disposition=stale" in caplog.text
    assert f"fallback={invalid_output}" in caplog.text
    assert (
        "PRIVATE_GENERATED_ANSWER" not in caplog.text
        and "SECRET_PLAYER_CONTENT" not in caplog.text
    )


def test_same_uuid_in_flight_and_after_commit_preserves_idempotency(world):
    game, peer, a, b, save, repo, install = world
    device_b = peer.login(a)
    assert device_b.account_id == a.account_id and device_b.token != a.token
    release, entered = Event(), Event()
    provider = blocking_provider(release, entered, fake_reply)
    install(provider)
    body = talk(save)
    with ThreadPoolExecutor(1) as executor:
        pending = executor.submit(game.post, a, save, body)
        try:
            assert entered.wait(5)
            still_running = game.post(device_b, save, body)
            assert error(still_running, 503, "NARRATIVE_IN_PROGRESS")["retryable"]
            changed = body | {"args": {"question": "Different question"}}
            error(game.post(device_b, save, changed), 409, "REQUEST_ID_REUSED")
            assert peer.receipt(device_b, save, body["request_id"]) == {
                "accepted": False
            }
        finally:
            release.set()
        first = ok(pending.result(timeout=5))
    repeated = ok(game.post(device_b, save, body))
    assert first["receipt"]["duplicate"] is False
    assert repeated["receipt"] == first["receipt"] | {"duplicate": True}
    assert repeated["save"] == first["save"] and repeated["audio_events"] == []
    assert (
        error(game.post(device_b, save, changed), 409, "REQUEST_ID_REUSED")["retryable"]
        is False
    )
    assert len(provider.calls) == 1
    assert game.read(b, save)["personal"]["dialogue"] == []
    stored = repo.get_save(save["id"])
    assert stored.version == len(stored.receipts) == len(stored.dialogues) == 1
    assert stored.dialogues[0].mode == "provider"


def test_different_uuids_share_no_graph_state_and_only_one_can_commit(world):
    game, peer, a, b, save, repo, install = world
    barrier = Barrier(2)

    def produce(request):
        barrier.wait(timeout=4)
        return fake_reply(request, text="reply_for_" + request.context.role)

    provider = FakeProvider(produce)
    install(provider)
    commands = talk(save, "owner only"), talk(save, "partner only")
    with ThreadPoolExecutor(2) as executor:
        pending = [
            executor.submit(game.post, actor, save, body)
            for actor, body in zip((a, b), commands, strict=True)
        ]
        responses = [f.result(timeout=8) for f in pending]
    assert sorted(r.status_code for r in responses) == [200, 409]
    assert sorted((r.context.role, r.context.question) for r in provider.calls) == [
        ("a", "owner only"),
        ("b", "partner only"),
    ]
    winner = next(i for i, value in enumerate(responses) if value.status_code == 200)
    loser = 1 - winner
    error(responses[loser], 409, "VERSION_CONFLICT")
    players, roles = (a, b), ("a", "b")
    accepted = ok(responses[winner])
    assert accepted["receipt"]["request_id"] == commands[winner]["request_id"]
    assert (
        accepted["save"]["personal"]["dialogue"][0]["answer"]
        == "reply_for_" + roles[winner]
    )
    assert peer.receipt(players[loser], save, commands[loser]["request_id"]) == {
        "accepted": False
    }
    assert peer.read(players[loser], save)["personal"]["dialogue"] == []
    stored = repo.get_save(save["id"])
    assert stored.version == 1 and len(stored.dialogues) == len(stored.receipts) == 1


def test_revoked_cookie_is_rechecked_after_generation_before_commit(world):
    game, peer, a, _, save, repo, install = world
    backup = peer.login(a)
    release, entered = Event(), Event()
    provider = blocking_provider(release, entered, fake_reply)
    install(provider)
    initial = repo.get_save(save["id"])
    body = talk(save)
    with ThreadPoolExecutor(1) as executor:
        pending = executor.submit(game.post, a, save, body)
        try:
            assert entered.wait(5)
            logout = peer.http.delete("/api/sessions/current", headers=a.headers)
            assert logout.status_code == 204
            assert not pending.done()
        finally:
            release.set()
        error(pending.result(timeout=5), 401, "UNAUTHENTICATED")
    assert len(provider.calls) == 1
    assert peer.receipt(backup, save, body["request_id"]) == {"accepted": False}
    assert repo.get_save(save["id"]) == initial


def test_fallback_failure_does_not_write(world, monkeypatch):
    game, peer, a, b, save, repo, install = world
    provider = FakeProvider(lambda req: fake_reply(req, game_fact=True))
    install(provider)
    monkeypatch.setattr("twoworlds.ai.graph.fallback_reply", lambda _: {"text": ""})
    initial = repo.get_save(save["id"])
    body = talk(save)
    result = game.post(a, save, body)
    error(result, 503, "NARRATIVE_UNAVAILABLE")
    assert "SECRET_PLAYER_CONTENT" not in result.text
    assert len(provider.calls) == 1
    assert repo.get_save(save["id"]) == initial
    assert peer.receipt(a, save, body["request_id"]) == {"accepted": False}
    assert peer.accept(b, save, "inspect", {"target": "sea_chart"})["version"] == 1


def test_fallback_loses_a_real_cas_after_final_version_check(world, monkeypatch):
    game, peer, a, b, save, repo, install = world
    provider = FakeProvider(lambda req: fake_reply(req, text=""))
    install(provider)
    at_cas, release = Event(), Event()
    real_cas = repo.compare_and_swap_save
    outcomes = []

    def aligned_cas(save_id, version, candidate):
        assert candidate.dialogues[-1].mode == "fallback"
        at_cas.set()
        assert release.wait(5)
        outcome = real_cas(save_id, version, candidate)
        outcomes.append(outcome)
        return outcome

    monkeypatch.setattr(repo, "compare_and_swap_save", aligned_cas)
    body = talk(save)
    with ThreadPoolExecutor(1) as executor:
        pending = executor.submit(game.post, a, save, body)
        try:
            assert at_cas.wait(5)
            assert (
                peer.accept(b, save, "inspect", {"target": "sea_chart"})["version"] == 1
            )
            winner = repo.get_save(save["id"])
        finally:
            release.set()
        error(pending.result(timeout=5), 409, "VERSION_CONFLICT")
    assert outcomes == [False]
    assert len(provider.calls) == 1
    assert winner.dialogues == () and repo.get_save(save["id"]) == winner
    assert game.receipt(a, save, body["request_id"]) == {"accepted": False}


def test_timeout_persists_only_demo_fallback_and_late_text_cannot_write(world, caplog):
    game, peer, a, b, save, repo, install = world
    release, entered, finished = Event(), Event(), Event()

    def respond(request):
        try:
            return fake_reply(request)
        finally:
            finished.set()

    provider = blocking_provider(release, entered, respond)
    install(provider, NarrativeLimits(timeout_seconds=0.15, max_concurrent=1))
    u = talk(save)
    try:
        with caplog.at_level(logging.INFO, logger="twoworlds.ai.graph"):
            accepted = ok(game.post(a, save, u))
            wait_for_log(caplog, "error=timeout")
        assert entered.is_set() and not finished.is_set()
        turn = accepted["save"]["personal"]["dialogue"][0]
        assert turn["mode"] == "fallback" and turn["answer"] == DEMO_ANSWER
        assert "error=timeout" in caplog.text and "usage=unknown" in caplog.text
        # The hung worker still occupies its slot. Neither it nor the original
        # request prevents an ordinary action on the same real database.
        advanced = peer.accept(b, accepted["save"], "inspect", {"target": "sea_chart"})
        assert advanced["version"] == 2
        after = repo.get_save(save["id"])
    finally:
        release.set()
    assert finished.wait(5)
    assert repo.get_save(save["id"]) == after
    repeat = ok(game.post(a, save, u))
    assert repeat["receipt"]["duplicate"] and repeat["save"]["version"] == 2
    assert len(provider.calls) == 1
    assert repeat["save"]["personal"]["dialogue"][0]["answer"] == DEMO_ANSWER
    assert "PRIVATE_GENERATED_ANSWER" not in caplog.text
