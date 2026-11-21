"""Kill a real API process after a successful CAS and before any HTTP response."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from functools import partial
import json
from threading import Barrier
from uuid import uuid4

import httpx
import pytest
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import connect

from tests.contracts.support import Platform, command, error, ok
from tests.identity_support import ORIGIN, unique_email
from tests.restart_support import config, register, server, stage_clock, until
from tests.storage.conftest import mongo_database  # noqa: F401
from twoworlds.application.commands import GameCommand
from twoworlds.storage.mongo import MongoRepository
from twoworlds.storage.sqlite import SQLiteRepository


def open_socket(address, actor, save):
    return connect(
        address.replace("http:", "ws:", 1) + f"/api/ws/saves/{save['id']}",
        origin=ORIGIN,
        additional_headers={"Cookie": actor.headers["Cookie"]},
        proxy=None,
        open_timeout=5,
    )


def snapshot(socket):
    message = json.loads(socket.recv(timeout=5))
    assert set(message) == {"type", "save"}
    assert message["type"] == "snapshot"
    assert "audio_events" not in message["save"]
    return message["save"]


@pytest.mark.parametrize("backend", ["sqlite", "mongo"])
def test_killed_api_process_recovers_receipt_and_private_views(
    tmp_path, request, backend
):
    if backend == "mongo":
        db, uri = request.getfixturevalue("mongo_database")
        mongo = uri, db.name
        repository = partial(MongoRepository, *mongo)
    else:
        mongo = None
        repository = partial(SQLiteRepository, tmp_path / "recovery.sqlite")
    env, address = config(tmp_path, backend, mongo)
    with (
        httpx.Client(base_url=address, trust_env=False, timeout=15) as http,
        httpx.Client(base_url=address, trust_env=False, timeout=15) as peer_http,
        ThreadPoolExecutor(2) as pool,
    ):
        game, peer = Platform(http, lambda: None), Platform(peer_http, lambda: None)
        with server(tmp_path, env, address) as first:
            owner = register(http, tmp_path, unique_email(), "设备 A")
            partner = register(http, tmp_path, unique_email(), "搭档")
            device_b = peer.login(owner)
            assert device_b.account_id == owner.account_id
            assert device_b.token != owner.token
            _, _, pair = game.pair(a=owner, b=partner)
            save = stage_clock(game, game.save(owner, pair), owner, partner)
            other_save = game.save(owner, pair, "starline")
            envelope = command(save, "repair_clock", {"mode": "steady"})
            request_id = envelope["request_id"]

            with open_socket(address, owner, save) as old:
                assert snapshot(old) == save
                arm = tmp_path / "hold-response"
                arm.touch()
                lost = pool.submit(game.post, owner, save, envelope)
                until((tmp_path / "committed").exists)
                assert first.poll() is None and not lost.done()

                owner_view, partner_view = (
                    peer.read(device_b, save),
                    peer.read(partner, save),
                )
                before = peer.receipt(device_b, save, request_id)
                assert before == {
                    "accepted": True,
                    "request_id": request_id,
                    "accepted_version": 9,
                }
                with closing(repository()) as db:
                    persisted = db.get_save(save["id"])
                assert (
                    persisted.version
                    == persisted.state.version
                    == persisted.public_history.through_version
                    == len(persisted.receipts)
                    == 9
                )
                stored = persisted.receipts[-1]
                assert stored.actor_id == owner.account_id
                assert str(stored.request_id) == request_id
                assert stored.accepted_version == 9
                assert (
                    stored.fingerprint
                    == GameCommand.model_validate(envelope).fingerprint()
                )

                first.kill()
                assert first.wait(timeout=5) != 0
                with pytest.raises(httpx.RemoteProtocolError):
                    lost.result(timeout=5)
                with pytest.raises(ConnectionClosed):
                    old.recv(timeout=5)
                arm.unlink()

        with server(tmp_path, env, address) as restarted:
            assert restarted.pid != first.pid
            with closing(repository()) as db:
                assert db.get_save(save["id"]) == persisted

            barrier = Barrier(2)

            def lookup(client, actor):
                barrier.wait(timeout=5)
                return client.receipt(actor, save, request_id)

            lookups = [
                pool.submit(lookup, game, owner),
                pool.submit(lookup, peer, device_b),
            ]
            assert [lookup.result(timeout=5) for lookup in lookups] == [before, before]
            assert game.receipt(partner, save, request_id) == {"accepted": False}
            assert game.receipt(owner, other_save, request_id) == {"accepted": False}
            assert game.receipt(owner, save, str(uuid4())) == {"accepted": False}
            assert game.read(owner, save) == peer.read(device_b, save) == owner_view
            assert game.read(partner, save) == partner_view
            assert owner_view["role"] == "a" and partner_view["role"] == "b"
            a_clues = {clue["id"] for clue in owner_view["personal"]["clues"]}
            b_clues = {clue["id"] for clue in partner_view["personal"]["clues"]}
            assert a_clues and b_clues and a_clues.isdisjoint(b_clues)
            assert "state" not in owner_view and "receipts" not in partner_view

            repeated = ok(peer.post(device_b, save, envelope))
            assert repeated["receipt"] == {
                "request_id": request_id,
                "status": "accepted",
                "accepted_version": 9,
                "duplicate": True,
            }
            assert repeated["save"] == owner_view and repeated["audio_events"] == []
            with closing(repository()) as db:
                assert db.get_save(save["id"]) == persisted

            with (
                open_socket(address, owner, save) as a,
                open_socket(address, device_b, save) as b,
                open_socket(address, partner, save) as c,
            ):
                assert snapshot(a) == snapshot(b) == owner_view
                assert snapshot(c) == partner_view
                # The partner's same UUID is a separate command, and neither
                # device can confuse its accepted version with the original.
                advanced = game.accept(
                    partner, partner_view, "confirm_route", {}, request_id
                )
                assert advanced["version"] == 10
                assert snapshot(a) == snapshot(b) == game.read(owner, save)
                assert snapshot(c) == advanced
                assert game.receipt(owner, save, request_id) == before
                assert game.receipt(partner, save, request_id) == before | {
                    "accepted_version": 10
                }

            advanced_starline = game.accept(
                owner, other_save, "inspect", {"target": "station_log"}, request_id
            )
            assert advanced_starline["version"] == 1
            assert peer.receipt(device_b, other_save, request_id) == before | {
                "accepted_version": 1
            }
            assert game.receipt(partner, other_save, request_id) == {"accepted": False}
            assert game.receipt(owner, save, request_id) == before
            assert not error(
                peer.post(device_b, save, envelope | {"args": {"mode": "fast"}}),
                409,
                "REQUEST_ID_REUSED",
            )["retryable"]
