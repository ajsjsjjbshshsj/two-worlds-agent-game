"""Real HTTP + independent SQLite/Mongo repositories; no rule/API mocks."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from threading import Barrier
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from tests.api import test_saves as lifecycle
from tests.contracts.support import Platform, command, error, ok
from twoworlds.api.app import create_app

save_apps = lifecycle.save_apps
save_repository_factory = lifecycle.save_repository_factory
sqlite_repository_factory = lifecycle.sqlite_repository_factory


@pytest.fixture
def world(save_apps):
    factory, store, publish, script = save_apps
    client, repo = factory()
    game = Platform(client, lambda: None)
    a, b, pair = game.pair()
    save = ok(
        client.post(
            "/api/saves",
            headers=a.headers,
            json={
                "pair_id": pair["id"],
                "script_id": "lighthouse",
                "script_version": "1.0.0",
            },
        )
    )
    return game, a, b, pair, save, repo, factory, script, store


def test_receipt_precedes_version_and_returns_current_private_snapshot(world):
    game, a, b, _, initial, repo, _, script, _ = world
    payload = command(initial, "inspect", {"target": "maintenance_log"})
    first_response = game.post(a, initial, payload)
    first = ok(first_response)
    assert first_response.headers["cache-control"] == "no-store"
    current = game.accept(b, first["save"], "inspect", {"target": "sea_chart"})
    before = repo.get_save(initial["id"])
    assert (
        before.version
        == before.state.version
        == before.public_history.through_version
        == 2
    )
    assert [r.accepted_version for r in before.receipts] == [1, 2]
    assert [r.actor_id for r in before.receipts] == [a.account_id, b.account_id]
    duplicate = ok(game.post(a, initial, payload))
    assert duplicate["receipt"] == {**first["receipt"], "duplicate": True}
    assert duplicate["save"] == game.read(a, current)
    assert duplicate["save"]["version"] == 2
    assert duplicate["receipt"]["accepted_version"] == 1
    assert repo.get_save(initial["id"]) == before
    assert game.receipt(b, initial, payload["request_id"]) == {"accepted": False}
    found = game.receipt(a, initial, payload["request_id"])
    assert found == {
        "accepted": True,
        "request_id": payload["request_id"],
        "accepted_version": 1,
    }
    assert "fingerprint" not in json.dumps(found)
    for clue in script.clues:
        if clue.role == "b":
            assert clue.text not in json.dumps(duplicate, ensure_ascii=False)


@pytest.mark.parametrize(
    "changes",
    [
        {"kind": "set_emitter", "args": {"angle": 90, "pattern": "pulse"}},
        {"args": {"target": "clock_gears"}},
        {"expected_version": 1},
    ],
)
def test_reused_id_changed_payload_is_rejected_before_rule_or_version(world, changes):
    game, a, _, _, save, repo, _, _, _ = world
    payload = command(save, "inspect", {"target": "maintenance_log"})
    ok(game.post(a, save, payload))
    before = repo.get_save(save["id"])
    assert len(before.receipts) == 1
    assert (before.receipts[0].actor_id, str(before.receipts[0].request_id)) == (
        a.account_id,
        payload["request_id"],
    )
    error(game.post(a, save, payload | changes), 409, "REQUEST_ID_REUSED")
    assert repo.get_save(save["id"]) == before


def test_same_uuid_is_independent_per_actor_and_per_save(
    world, save_repository_factory
):
    """The full key is (save_id, actor_id, request_id), including concurrent retries."""
    from twoworlds.application.commands import GameCommand

    game, a, b, _, save, repo, factory, _, _ = world
    request_id = str(uuid4())
    next_save = game.accept(
        a, save, "inspect", {"target": "maintenance_log"}, request_id
    )
    game.accept(b, next_save, "inspect", {"target": "sea_chart"}, request_id)
    assert game.receipt(a, save, request_id)["accepted_version"] == 1
    assert game.receipt(b, save, request_id)["accepted_version"] == 2
    _, _, other_pair = game.pair(a=a, b=b)
    other = ok(
        game.http.post(
            "/api/saves",
            headers=a.headers,
            json={
                "pair_id": other_pair["id"],
                "script_id": "lighthouse",
                "script_version": "1.0.0",
            },
        )
    )
    assert game.receipt(a, other, request_id) == {"accepted": False}
    other = game.accept(a, other, "inspect", {"target": "maintenance_log"})
    # A can reuse its UUID with different content in a different save. The same
    # content change within either save must still be REQUEST_ID_REUSED.
    first_body = command(
        {"version": 0}, "inspect", {"target": "maintenance_log"}, request_id
    )
    second_body = command(
        other, "set_emitter", {"angle": 90, "pattern": "pulse"}, request_id
    )
    other = ok(game.post(a, other, second_body))["save"]
    first, second = repo.get_save(save["id"]), repo.get_save(other["id"])
    for stored in (first, second):
        assert (
            stored.version
            == stored.state.version
            == stored.public_history.through_version
            == 2
        )
        assert [r.accepted_version for r in stored.receipts] == [1, 2]
    assert [(r.actor_id, str(r.request_id)) for r in first.receipts] == [
        (a.account_id, request_id),
        (b.account_id, request_id),
    ]
    assert second.receipts[-1].actor_id == a.account_id
    assert str(second.receipts[-1].request_id) == request_id
    assert (
        first.receipts[0].fingerprint
        == GameCommand.model_validate(first_body).fingerprint()
    )
    assert (
        second.receipts[-1].fingerprint
        == GameCommand.model_validate(second_body).fingerprint()
    )
    assert first.receipts[0].fingerprint != second.receipts[-1].fingerprint
    assert first.state.discovered_clues == ("a_maintenance_log", "b_sea_chart")
    assert second.state.device("emitter", "angle") == 90

    independent_repo = save_repository_factory()
    assert independent_repo is not repo
    client, _ = factory(independent_repo)
    second_game = Platform(client, lambda: None)
    with ThreadPoolExecutor(2) as pool:
        pending = [
            pool.submit(game.post, a, save, first_body),
            pool.submit(second_game.post, a, other, second_body),
        ]
        results = [ok(f.result(timeout=25)) for f in pending]
    assert [r["receipt"]["duplicate"] for r in results] == [True, True]
    assert [r["receipt"]["accepted_version"] for r in results] == [1, 2]
    assert [r["save"]["id"] for r in results] == [first.id, second.id]
    error(
        game.post(a, other, second_body | {"args": {"angle": 180, "pattern": "pulse"}}),
        409,
        "REQUEST_ID_REUSED",
    )
    assert game.receipt(a, save, request_id)["accepted_version"] == 1
    assert game.receipt(a, other, request_id)["accepted_version"] == 2
    assert game.receipt(b, other, request_id) == {"accepted": False}
    # Every retry/query/rejected reuse preserves both complete aggregates.
    assert repo.get_save(first.id) == independent_repo.get_save(first.id) == first
    assert repo.get_save(second.id) == independent_repo.get_save(second.id) == second


@pytest.mark.parametrize(
    "changes",
    [
        {"role": "b"},
        {"account_id": "other"},
        {"state": {}},
        {"completed": True},
        {"expected_version": True},
        {"expected_version": -1},
        {"expected_version": "0"},
        {"request_id": "not-a-uuid"},
        {"request_id": 1},
        {"kind": 1},
        {"args": []},
        {"args": {"target": "maintenance_log", "completed": True}},
    ],
)
def test_invalid_payload_never_writes_or_creates_receipt(world, changes):
    game, a, _, _, save, repo, _, _, _ = world
    before = repo.get_save(save["id"])
    payload = command(save, "inspect", {"target": "maintenance_log"}) | changes
    response = game.post(a, save, payload)
    error(response, 422)
    assert response.headers["cache-control"] == "no-store"
    assert repo.get_save(save["id"]) == before


@pytest.mark.parametrize(
    "role,kind,args",
    [
        ("a", "set_filter", {"filter": "amber"}),
        ("b", "set_emitter", {"angle": 90, "pattern": "pulse"}),
        ("a", "set_emitter", {"angle": 90, "pattern": "pulse"}),
        ("b", "lock_signal", {}),
        ("a", "inspect", {"target": "clock_gears"}),
        ("a", "inspect", {"target": "bogus"}),
    ],
)
def test_rule_rejection_is_atomic(world, role, kind, args):
    game, a, b, _, save, repo, _, _, _ = world
    before = repo.get_save(save["id"])
    actor = a if role == "a" else b
    payload = command(save, kind, args)
    error(game.post(actor, save, payload), 422)
    assert repo.get_save(save["id"]) == before
    assert game.receipt(actor, save, payload["request_id"]) == {"accepted": False}


def test_noop_invalid_configuration_stale_and_unauthorized(world):
    game, a, b, _, initial, repo, _, _, _ = world
    current = game.accept(a, initial, "inspect", {"target": "maintenance_log"})
    before = repo.get_save(current["id"])
    for args in ({"angle": 0, "pattern": "steady"}, {"angle": 45, "pattern": "pulse"}):
        error(game.post(a, current, command(current, "set_emitter", args)), 422)
    error(
        game.post(b, initial, command(initial, "inspect", {"target": "sea_chart"})),
        409,
        "VERSION_CONFLICT",
    )
    outsider = game.account("外人")
    payload = command(current, "inspect", {"target": "sea_chart"})
    error(game.post(outsider, current, payload), 404, "SAVE_NOT_FOUND")
    error(
        game.http.get(
            f"/api/saves/{current['id']}/receipts/{payload['request_id']}",
            headers=outsider.headers,
        ),
        404,
        "SAVE_NOT_FOUND",
    )
    error(game.http.post(f"/api/saves/{current['id']}/commands", json=payload), 401)
    error(
        game.http.get(f"/api/saves/{current['id']}/receipts/{payload['request_id']}"),
        401,
    )
    error(
        game.http.get(
            f"/api/saves/{current['id']}/receipts/not-uuid", headers=a.headers
        ),
        422,
    )
    assert repo.get_save(current["id"]) == before


class CommitBarrier:
    """Only align real CAS writes; both repositories and commit results are real."""

    def __init__(self, repository, barrier):
        self.repository, self.barrier = repository, barrier

    def __getattr__(self, name):
        return getattr(self.repository, name)

    def compare_and_swap_save(self, save_id, expected_version, candidate):
        self.barrier.wait(timeout=15)
        return self.repository.compare_and_swap_save(
            save_id, expected_version, candidate
        )


@pytest.mark.parametrize("same_request", [False, True])
def test_independent_apps_compete_at_real_database_cas(
    world, save_repository_factory, same_request
):
    game, a, b, _, save, repo, factory, _, _ = world
    second_repo = save_repository_factory()
    assert second_repo is not repo
    barrier = Barrier(2)
    first_client, _ = factory(CommitBarrier(repo, barrier))
    second_client, _ = factory(CommitBarrier(second_repo, barrier))
    payload = command(save, "inspect", {"target": "maintenance_log"})
    other_payload = (
        payload if same_request else command(save, "inspect", {"target": "sea_chart"})
    )
    with ThreadPoolExecutor(2) as pool:
        pending = [
            pool.submit(
                first_client.post,
                f"/api/saves/{save['id']}/commands",
                headers=a.headers,
                json=payload,
            ),
            pool.submit(
                second_client.post,
                f"/api/saves/{save['id']}/commands",
                headers=(a if same_request else b).headers,
                json=other_payload,
            ),
        ]
        responses = [f.result(timeout=25) for f in pending]
    assert sorted(r.status_code for r in responses) == (
        [200, 200] if same_request else [200, 409]
    )
    current = repo.get_save(save["id"])
    assert (
        current.version
        == current.state.version
        == current.public_history.through_version
        == 1
    )
    assert len(current.receipts) == 1
    from twoworlds.application.commands import GameCommand

    winner = next(r.json() for r in responses if r.status_code == 200)
    actor, body = (
        (a, payload)
        if current.receipts[0].actor_id == a.account_id
        else (b, other_payload)
    )
    assert current.receipts[0].actor_id == actor.account_id
    assert str(current.receipts[0].request_id) == body["request_id"]
    assert (
        current.receipts[0].fingerprint
        == GameCommand.model_validate(body).fingerprint()
    )
    assert current.receipts[0].accepted_version == winner["save"]["version"] == 1
    assert current.state.discovered_clues == (
        "a_maintenance_log" if actor == a else "b_sea_chart",
    )
    if same_request:
        assert sorted(r.json()["receipt"]["duplicate"] for r in responses) == [
            False,
            True,
        ]
    else:
        error(
            next(r for r in responses if r.status_code == 409), 409, "VERSION_CONFLICT"
        )
        for actor, body in ((a, payload), (b, other_payload)):
            assert game.receipt(actor, save, body["request_id"])["accepted"] == (
                actor.account_id == current.receipts[0].actor_id
            )


@pytest.mark.parametrize("ending", ["guide_now", "wait_tide"])
def test_full_lighthouse_http_cooperation_both_endings(world, ending):
    game, a, b, _, save, repo, _, script, _ = world
    save = game.accept(a, save, "inspect", {"target": "maintenance_log"})
    save = game.accept(b, save, "inspect", {"target": "sea_chart"})
    save = game.accept(a, save, "share_clue", {"clue_id": "a_maintenance_log"})
    save = game.accept(b, save, "set_filter", {"filter": "amber"})
    before_b = game.read(b, save)["personal"]["observations"]
    save = game.accept(a, save, "set_emitter", {"angle": 180, "pattern": "pulse"})
    mountain = game.read(b, save)["personal"]["observations"]
    assert mountain != before_b
    assert "观测山" in next(o["text"] for o in mountain if o["topic"] == "beam")
    save = game.accept(a, save, "set_emitter", {"angle": 90, "pattern": "pulse"})
    bay = game.read(b, save)["personal"]["observations"]
    assert bay != mountain
    assert "内湾航道" in next(o["text"] for o in bay if o["topic"] == "beam")
    save = game.accept(b, save, "lock_signal")
    unpowered = game.read(a, save)["personal"]["observations"]
    save = game.accept(b, save, "route_power", {"target": "tower"})
    assert game.read(a, save)["personal"]["observations"] != unpowered
    save = game.accept(a, save, "inspect", {"target": "clock_gears"})
    save = game.accept(a, save, "repair_clock", {"mode": "steady"})
    save = game.accept(b, save, "confirm_route")
    save = game.accept(a, save, "vote_ending", {"choice": ending})
    other = "wait_tide" if ending == "guide_now" else "guide_now"
    save = game.accept(b, save, "vote_ending", {"choice": other})
    assert not save["completed"]
    save = game.accept(b, save, "vote_ending", {"choice": ending})
    assert save["completed"] and save["public"]["ending"] == ending
    own, partner = game.read(a, save), game.read(b, save)
    assert own["public"] == partner["public"]
    for clue in script.clues:
        if clue.role == "b":
            assert clue.text not in json.dumps(own, ensure_ascii=False)
            assert clue.text not in json.dumps(
                own["public"]["recap"], ensure_ascii=False
            )
    before = repo.get_save(save["id"])
    last = before.receipts[-1]
    duplicate = ok(
        game.post(
            b,
            save,
            {
                "request_id": str(last.request_id),
                "expected_version": save["version"] - 1,
                "kind": "vote_ending",
                "args": {"choice": ending},
            },
        )
    )
    assert duplicate["receipt"]["duplicate"] and duplicate["save"]["completed"]
    assert duplicate["save"]["version"] == save["version"]
    error(
        game.post(a, save, command(save, "vote_ending", {"choice": other})),
        422,
        "SAVE_COMPLETED",
    )
    assert repo.get_save(save["id"]) == before


def test_closed_app_restores_identity_receipts_and_old_request(
    save_repository_factory, published_story
):
    store, publish = published_story
    publish()
    now = datetime(2026, 11, 15, tzinfo=timezone.utc)

    def app(repository):
        return create_app(
            repository=repository,
            publication_store=store,
            identity_clock=lambda: now,
            rate_limit=100,
        )

    original_repo = save_repository_factory()
    with TestClient(app(original_repo)) as client:
        game = Platform(client, lambda: None)
        a, b, pair = game.pair()
        save = ok(
            client.post(
                "/api/saves",
                headers=a.headers,
                json={
                    "pair_id": pair["id"],
                    "script_id": "lighthouse",
                    "script_version": "1.0.0",
                },
            )
        )
        payload = command(save, "inspect", {"target": "maintenance_log"})
        first = ok(game.post(a, save, payload))
        current = game.accept(b, first["save"], "inspect", {"target": "sea_chart"})
        expected = game.read(a, current)
        stored_before = original_repo.get_save(save["id"])
    reopened_repo = save_repository_factory()
    assert reopened_repo is not original_repo
    with TestClient(app(reopened_repo)) as client:
        game = Platform(client, lambda: None)
        restored = game.recover(a)
        assert restored.account_id == a.account_id and restored.token != a.token
        assert game.read(restored, save) == expected
        assert (
            game.receipt(restored, save, payload["request_id"])["accepted_version"] == 1
        )
        retry = ok(game.post(restored, save, payload))
        assert retry["receipt"]["duplicate"] and retry["save"] == expected
        stored_after = reopened_repo.get_save(save["id"])
        assert stored_after == stored_before
        assert stored_after.version == stored_after.public_history.through_version == 2
        assert [r.accepted_version for r in stored_after.receipts] == [1, 2]
        assert stored_after.receipts[0].actor_id == restored.account_id
        assert str(stored_after.receipts[0].request_id) == payload["request_id"]


def test_unfilled_pair_has_readonly_opening(world):
    game, a, _, _, _, repo, _, _, _ = world
    pair = ok(game.http.post("/api/pairs", headers=a.headers))
    save = ok(
        game.http.post(
            "/api/saves",
            headers=a.headers,
            json={
                "pair_id": pair["id"],
                "script_id": "lighthouse",
                "script_version": "1.0.0",
            },
        )
    )
    before = repo.get_save(save["id"])
    for kind, args in (
        ("inspect", {"target": "maintenance_log"}),
        ("talk", {"question": "你好"}),
    ):
        payload = command(save, kind, args)
        error(game.post(a, save, payload), 422, "PAIR_NOT_READY")
        assert game.receipt(a, save, payload["request_id"]) == {"accepted": False}
    assert game.read(a, save)["scene_id"] == "calibration"
    assert repo.get_save(save["id"]) == before


def test_full_512_receipts_keep_old_confirmations_and_reject_new_commands(world):
    from twoworlds.application.commands import GameCommand
    from twoworlds.domain.engine import apply_command
    from twoworlds.domain.persistence import CommandReceipt, SaveRecord
    from twoworlds.domain.recap import append_public_history

    game, a, b, _, initial, repo, _, script, _ = world
    a, b, pair = game.pair(a=a, b=b)
    original = repo.get_save(initial["id"])
    state, history, receipts = original.state, original.public_history, []
    first_payload = None
    # Generate 512 actual valid domain transitions; no mocked versions or receipts.
    for index in range(512):
        actor = b if index == 1 else a
        if index < 2:
            kind, args = (
                "inspect",
                {"target": "sea_chart" if index == 1 else "maintenance_log"},
            )
        else:
            kind, args = (
                "set_emitter",
                {"angle": 90 if index % 2 == 0 else 180, "pattern": "pulse"},
            )
        body = command({"version": state.version}, kind, args)
        if index == 0:
            first_payload = body
        envelope = GameCommand.model_validate(body)
        state, events = apply_command(
            state, script, "b" if index == 1 else "a", {"kind": kind, "args": args}
        )
        history = append_public_history(history, script, state.version, events)
        receipts.append(
            CommandReceipt(
                actor_id=actor.account_id,
                request_id=envelope.request_id,
                fingerprint=envelope.fingerprint(),
                accepted_version=state.version,
                created_at=original.created_at,
            )
        )
    full = SaveRecord.model_validate(
        original.model_dump()
        | {
            "id": "save_full",
            "pair_id": pair["id"],
            "version": 512,
            "state": state,
            "public_history": history,
            "receipts": tuple(receipts),
        }
    )
    repo.create_save(full)
    view = game.read(a, {"id": full.id})
    assert view["version"] == 512
    duplicate = ok(game.post(a, view, first_payload))
    assert duplicate["receipt"]["duplicate"]
    assert duplicate["receipt"]["accepted_version"] == 1
    assert duplicate["save"]["version"] == 512
    payload = command(view, "set_emitter", {"angle": 0, "pattern": "steady"})
    error(game.post(a, view, payload), 409, "SAVE_COMMAND_LIMIT")
    error(
        game.post(a, view, first_payload | {"expected_version": 512}),
        409,
        "REQUEST_ID_REUSED",
    )
    assert game.receipt(a, view, payload["request_id"]) == {"accepted": False}
    assert (
        game.receipt(a, view, str(receipts[-1].request_id))["accepted_version"] == 512
    )
    assert game.receipt(b, view, str(receipts[-1].request_id)) == {"accepted": False}
    assert repo.get_save(full.id) == full


def test_competing_same_id_with_different_valid_payloads_cannot_overwrite(
    world, save_repository_factory
):
    game, a, _, _, save, repo, factory, _, _ = world
    save = game.accept(a, save, "inspect", {"target": "maintenance_log"})
    barrier = Barrier(2)
    clients = [
        factory(CommitBarrier(r, barrier))[0] for r in (repo, save_repository_factory())
    ]
    request_id = str(uuid4())
    bodies = [
        command(save, "set_emitter", {"angle": angle, "pattern": "pulse"}, request_id)
        for angle in (90, 180)
    ]
    with ThreadPoolExecutor(2) as pool:
        pending = [
            pool.submit(
                client.post,
                f"/api/saves/{save['id']}/commands",
                headers=a.headers,
                json=body,
            )
            for client, body in zip(clients, bodies)
        ]
        responses = [f.result(timeout=25) for f in pending]
    assert sorted(r.status_code for r in responses) == [200, 409]
    error(next(r for r in responses if r.status_code == 409), 409, "REQUEST_ID_REUSED")
    current = repo.get_save(save["id"])
    assert current.version == 2 and len(current.receipts) == 2
    winner = next(r for r in responses if r.status_code == 200)
    assert winner.json()["save"]["personal"]["devices"]["emitter"][
        "angle"
    ] == current.state.device("emitter", "angle")


def test_commit_succeeded_but_response_failed_can_be_confirmed(
    world, save_repository_factory
):
    from twoworlds.ports.repository import RepositoryError

    game, a, _, _, save, repo, factory, _, _ = world

    class LostResponse:
        def __getattr__(self, name):
            return getattr(repo, name)

        def compare_and_swap_save(self, save_id, expected_version, candidate):
            assert repo.compare_and_swap_save(save_id, expected_version, candidate)
            raise RepositoryError("SECRET_DRIVER_FAILURE_AFTER_COMMIT")

    lost, _ = factory(LostResponse())
    body = command(save, "inspect", {"target": "maintenance_log"})
    response = lost.post(
        f"/api/saves/{save['id']}/commands", headers=a.headers, json=body
    )
    error(response, 503, "DEPENDENCY_UNAVAILABLE")
    assert "SECRET_DRIVER_FAILURE_AFTER_COMMIT" not in response.text
    assert repo.get_save(save["id"]).version == 1
    fresh, _ = factory(save_repository_factory())
    repeated = ok(
        fresh.post(f"/api/saves/{save['id']}/commands", headers=a.headers, json=body)
    )
    assert repeated["receipt"]["duplicate"] and repeated["save"]["version"] == 1
    assert len(repo.get_save(save["id"]).receipts) == 1
