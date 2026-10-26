from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from .support import command, error, ok


def test_old_version_retry_confirms_receipt_and_returns_current_snapshot(
    client_factory,
):
    game = client_factory()
    a, b, pair = game.pair()
    initial = game.save(a, pair)
    payload = command(initial, "inspect", {"target": "maintenance_log"})
    first = ok(game.post(a, initial, payload))
    current = game.accept(b, first["save"], "inspect", {"target": "sea_chart"})
    retry = ok(game.post(a, initial, payload))
    assert retry["receipt"] == {**first["receipt"], "duplicate": True}
    assert retry["save"] == game.read(a, current)
    assert retry["save"]["version"] > retry["receipt"]["accepted_version"]
    receipt = game.receipt(a, initial, payload["request_id"])
    assert receipt["accepted"] is True
    assert receipt["accepted_version"] == first["receipt"]["accepted_version"]
    assert game.receipt(b, initial, payload["request_id"]) == {"accepted": False}


@pytest.mark.parametrize(
    "changes",
    [
        {"kind": "set_emitter", "args": {"angle": 90, "pattern": "pulse"}},
        {"args": {"target": "clock_gears"}},
        {"expected_version": 1},
    ],
    ids=["kind", "args", "original-version"],
)
def test_same_actor_cannot_reuse_id_with_changed_payload(client_factory, changes):
    game = client_factory()
    a, b, pair = game.pair()
    save = game.save(a, pair)
    payload = command(save, "inspect", {"target": "maintenance_log"})
    ok(game.post(a, save, payload))
    before = (game.read(a, save), game.read(b, save))
    error(game.post(a, save, {**payload, **changes}), 409, "REQUEST_ID_REUSED")
    assert (game.read(a, save), game.read(b, save)) == before


def test_same_request_id_is_independent_for_other_actor(client_factory):
    game = client_factory()
    a, b, pair = game.pair()
    save = game.save(a, pair)
    request_id = str(uuid4())
    save = game.accept(a, save, "inspect", {"target": "maintenance_log"}, request_id)
    save = game.accept(b, save, "inspect", {"target": "sea_chart"}, request_id)
    assert (
        game.receipt(a, save, request_id)["accepted_version"] + 1
        == (game.receipt(b, save, request_id)["accepted_version"])
    )


@pytest.mark.parametrize("same_request", [False, True], ids=["different", "identical"])
def test_two_application_instances_compete_on_one_database(
    client_factory, tmp_path, same_request
):
    path = tmp_path / "shared.db"
    first, second = client_factory(path), client_factory(path)
    a, b, pair = first.pair()
    save = first.save(a, pair)
    payload_a = command(save, "inspect", {"target": "maintenance_log"})
    actor_b = a if same_request else b
    payload_b = (
        payload_a if same_request else command(save, "inspect", {"target": "sea_chart"})
    )
    with ThreadPoolExecutor(2) as pool:
        pending = [
            pool.submit(first.post, a, save, payload_a),
            pool.submit(second.post, actor_b, save, payload_b),
        ]
        responses = [future.result(timeout=10) for future in pending]
    assert sorted(r.status_code for r in responses) == (
        [200, 200] if same_request else [200, 409]
    )
    assert first.read(a, save)["version"] == save["version"] + 1
    if same_request:
        assert sorted(r.json()["receipt"]["duplicate"] for r in responses) == [
            False,
            True,
        ]
    else:
        loser = next(r for r in responses if r.status_code == 409)
        error(loser, 409, "VERSION_CONFLICT")
        winner_id = next(r for r in responses if r.status_code == 200).json()[
            "receipt"
        ]["request_id"]
        for actor, payload in ((a, payload_a), (b, payload_b)):
            assert first.receipt(actor, save, payload["request_id"])["accepted"] == (
                payload["request_id"] == winner_id
            )


@pytest.mark.parametrize(
    "changes",
    [
        {"value": "legacy"},
        {"role": "b"},
        {"expected_version": -1},
        {"expected_version": True},
        {"request_id": "not-a-uuid"},
        {"args": {"target": "maintenance_log", "completed": True}},
    ],
    ids=["legacy-value", "client-role", "negative", "boolean", "bad-id", "extra-arg"],
)
def test_invalid_command_does_not_change_save_or_create_receipt(
    client_factory, changes
):
    game = client_factory()
    a, b, pair = game.pair()
    save = game.save(a, pair)
    before = (game.read(a, save), game.read(b, save))
    payload = {**command(save, "inspect", {"target": "maintenance_log"}), **changes}
    error(game.post(a, save, payload), 422)
    assert (game.read(a, save), game.read(b, save)) == before
    if changes.get("request_id") != "not-a-uuid":
        assert game.receipt(a, save, payload["request_id"]) == {"accepted": False}
