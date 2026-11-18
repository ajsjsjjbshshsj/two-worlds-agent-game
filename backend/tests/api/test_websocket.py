"""Exercise WebSockets through FastAPI and real SQLite/Mongo repositories."""

from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import json
import os
import socket
import subprocess
import sys
from threading import Event

import httpx
import pytest
from fastapi import WebSocketDisconnect
from fastapi.testclient import TestClient
from websockets.exceptions import ConnectionClosed, InvalidStatus
from websockets.sync.client import connect

from tests.contracts.support import Platform, ok
from tests.save_support import make_publications
from twoworlds.api.app import create_app
from twoworlds.realtime.protocol import WebSocketTiming
from twoworlds.storage.sqlite import SQLiteRepository


ORIGIN = "http://testserver"
URL = "/api/ws/saves/save_unknown"
HEARTBEAT = WebSocketTiming(heartbeat_interval=0.02, pong_timeout=1)


@pytest.fixture(scope="module")
def publications(tmp_path_factory):
    store, publish = make_publications(tmp_path_factory.mktemp("ws-publications"))
    publish()
    return store


@pytest.fixture
def now():
    return [datetime(2026, 11, 18, tzinfo=timezone.utc)]


@pytest.fixture
def open_game(tmp_path, publications, now):
    with ExitStack() as stack:

        def factory(*, timing=None, repo=None, finished=None):
            app = create_app(
                repository=repo
                if repo is not None
                else SQLiteRepository(tmp_path / "ws.db"),
                publication_store=publications,
                allowed_origins=[ORIGIN],
                identity_clock=lambda: now[0],
                websocket_timing=timing,
            )

            async def observe(scope, receive, send):
                try:
                    await app(scope, receive, send)
                finally:
                    if finished is not None and scope["type"] == "websocket":
                        finished.set()

            client = stack.enter_context(TestClient(observe))
            return Platform(client, stack.close)

        yield factory


def connect_save(game, save=None):
    url = URL if save is None else f"/api/ws/saves/{save['id']}"
    return game.http.websocket_connect(url, headers={"Origin": ORIGIN})


def authenticate(ws, actor):
    ws.send_json({"type": "auth", "token": actor.token})


def assert_close(ws, code):
    assert ws.receive() == {"type": "websocket.close", "code": code, "reason": ""}


@pytest.mark.parametrize("backend", ["sqlite", "mongo"])
def test_exact_origin_and_both_roles_receive_only_the_http_projection(
    open_game, request, backend
):
    repo = (
        request.getfixturevalue("mongo_repository_factory")()
        if backend == "mongo"
        else None
    )
    game = open_game(repo=repo)
    a, b, pair = game.pair()
    save = game.save(a, pair)
    save = game.accept(a, save, "inspect", {"target": "maintenance_log"})
    save = game.accept(b, save, "inspect", {"target": "sea_chart"})
    snapshots = {}
    for role, actor, partner in (("a", a, b), ("b", b, a)):
        with connect_save(game, save) as ws:
            authenticate(ws, actor)
            message = ws.receive_json()
            assert message == {"type": "snapshot", "save": game.read(actor, save)}
            snapshot = message["save"]
            assert snapshot["role"] == role
            assert (snapshot["script_id"], snapshot["script_version"]) == (
                "lighthouse",
                "1.0.0",
            )
            assert (
                snapshot["personal"]["clues"] and snapshot["personal"]["observations"]
            )
            assert not snapshot["personal"]["dialogue"]
            encoded = json.dumps(message, ensure_ascii=False)
            for secret in (
                a.token,
                b.token,
                a.recovery_key,
                b.recovery_key,
                partner.account_id,
            ):
                assert secret not in encoded
            assert (
                not {"state", "receipt", "receipts", "member_a", "member_b"}
                & snapshot.keys()
            )
            snapshots[role] = snapshot["personal"]
    for role, partner_role in (("a", "b"), ("b", "a")):
        personal, partner = snapshots[role], snapshots[partner_role]
        assert personal["devices"].keys().isdisjoint(partner["devices"])
        assert all(clue not in personal["clues"] for clue in partner["clues"])
        assert all(
            observation not in personal["observations"]
            for observation in partner["observations"]
        )


@pytest.mark.parametrize(
    "headers",
    [
        [],
        [("Origin", "null")],
        [("Origin", "*")],
        [("Origin", "http://testserver.evil.test")],
        [("Origin", "http://testserver:80")],
        [("Origin", ORIGIN), ("Origin", ORIGIN)],
    ],
)
def test_missing_wrong_or_ambiguous_origin_denies_upgrade(open_game, headers):
    game = open_game()
    with pytest.raises(WebSocketDisconnect) as rejected:
        with game.http.websocket_connect(URL, headers=httpx.Headers(headers)):
            pytest.fail("Rejected Origin upgraded")
    assert rejected.value.code == 4403


def test_query_credentials_deny_upgrade(open_game):
    game = open_game()
    actor = game.account()
    with pytest.raises(WebSocketDisconnect) as rejected:
        with game.http.websocket_connect(
            f"{URL}?token={actor.token}", headers={"Origin": ORIGIN}
        ):
            pytest.fail("Connection with URL credentials upgraded")
    assert rejected.value.code == 4403


def test_first_frame_has_a_deadline_and_http_credentials_do_not_authenticate(open_game):
    assert WebSocketTiming().auth_timeout == 10
    game = open_game(timing=WebSocketTiming(auth_timeout=0.02))
    actor = game.account()
    with game.http.websocket_connect(
        URL, headers={"Origin": ORIGIN, **actor.headers}
    ) as ws:
        assert_close(ws, 4401)


@pytest.mark.parametrize("credential", ["invalid", "recovery", "expired", "revoked"])
def test_inactive_or_non_session_credential_is_rejected_before_save_access(
    open_game, now, credential
):
    game = open_game()
    a, _, pair = game.pair()
    save = game.save(a, pair)
    token = a.token
    if credential == "invalid":
        token = "tw_session_" + "Z" * 43
    elif credential == "recovery":
        token = a.recovery_key
    elif credential == "expired":
        now[0] += timedelta(days=7)
    else:
        assert (
            game.http.delete("/api/sessions/current", headers=a.headers).status_code
            == 204
        )
    with connect_save(game, save) as ws:
        ws.send_json({"type": "auth", "token": token})
        assert_close(ws, 4401)


@pytest.mark.parametrize(
    ("frame", "code"),
    [
        ("{", 4400),
        ("[]", 4400),
        ('{"type":"pong","id":1}', 4400),
        ('{"type":"auth"}', 4400),
        ('{"type":"auth","token":true}', 4400),
        ('{"type":"auth","token":"one","token":"two"}', 4400),
        ("[" * 1100 + "]" * 1100, 4400),
        (b'{"type":"auth","token":"ignored"}', 4400),
        ("x" * 4097, 1009),
        ("界" * 1400, 1009),
    ],
)
def test_invalid_first_frame_closes_without_a_payload(open_game, frame, code):
    with connect_save(open_game()) as ws:
        if isinstance(frame, bytes):
            ws.send_bytes(frame)
        else:
            ws.send_text(frame)
        assert_close(ws, code)


def test_valid_token_does_not_allow_client_supplied_account_role_or_pair(open_game):
    game = open_game()
    a, b, pair = game.pair()
    save = game.save(a, pair)
    with connect_save(game, save) as ws:
        ws.send_json(
            {
                "type": "auth",
                "token": b.token,
                "role": "a",
                "account_id": a.account_id,
                "pair_id": pair["id"],
            }
        )
        assert_close(ws, 4400)


def test_repeat_auth_cannot_switch_connection_identity(open_game):
    game = open_game()
    a, b, pair = game.pair()
    save = game.save(a, pair)
    with connect_save(game, save) as ws:
        authenticate(ws, a)
        assert ws.receive_json()["save"]["role"] == "a"
        authenticate(ws, b)
        assert_close(ws, 4400)


@pytest.mark.parametrize("backend", ["sqlite", "mongo"])
def test_nonmember_and_missing_save_close_identically(open_game, request, backend):
    repo = (
        request.getfixturevalue("mongo_repository_factory")()
        if backend == "mongo"
        else None
    )
    game = open_game(repo=repo)
    a, _, pair = game.pair()
    save = game.save(a, pair)
    outsider = game.account()
    for target, actor in ((save, outsider), (None, a)):
        with connect_save(game, target) as ws:
            authenticate(ws, actor)
            assert_close(ws, 4404)


@pytest.mark.parametrize("backend", ["sqlite", "mongo"])
def test_reconnect_reads_a_new_projection_after_an_http_commit(
    open_game, request, backend
):
    repo = (
        request.getfixturevalue("mongo_repository_factory")()
        if backend == "mongo"
        else None
    )
    game = open_game(repo=repo)
    a, _, pair = game.pair()
    save = game.save(a, pair)
    with connect_save(game, save) as ws:
        authenticate(ws, a)
        assert ws.receive_json() == {"type": "snapshot", "save": save}
    next_save = game.accept(a, save, "inspect", {"target": "maintenance_log"})
    with connect_save(game, save) as ws:
        authenticate(ws, a)
        assert ws.receive_json() == {"type": "snapshot", "save": next_save}


def first_ping(ws, actor):
    authenticate(ws, actor)
    assert ws.receive_json()["type"] == "snapshot"
    assert ws.receive_json() == {"type": "ping", "id": 1}


def test_matching_pong_keeps_the_same_connection_open(open_game):
    game = open_game(timing=HEARTBEAT)
    a, _, pair = game.pair()
    save = game.save(a, pair)
    with connect_save(game, save) as ws:
        first_ping(ws, a)
        ws.send_json({"type": "pong", "id": 1})
        assert ws.receive_json() == {"type": "ping", "id": 2}
        ws.send_json({"type": "pong", "id": 2})


@pytest.mark.parametrize("bad_id", [2, True, "1"])
def test_pong_must_match_the_outstanding_ping(open_game, bad_id):
    game = open_game(timing=HEARTBEAT)
    a, _, pair = game.pair()
    with connect_save(game, game.save(a, pair)) as ws:
        first_ping(ws, a)
        ws.send_json({"type": "pong", "id": bad_id})
        assert_close(ws, 4400)


def test_missing_pong_closes_the_connection(open_game):
    game = open_game(timing=WebSocketTiming(heartbeat_interval=0.02, pong_timeout=0.02))
    a, _, pair = game.pair()
    with connect_save(game, game.save(a, pair)) as ws:
        first_ping(ws, a)
        assert_close(ws, 4408)


@pytest.mark.parametrize("logout", [False, True], ids=["expired", "revoked"])
def test_heartbeat_reauthenticates_an_already_verified_connection(
    open_game, now, logout
):
    game = open_game(timing=HEARTBEAT)
    a, _, pair = game.pair()
    with connect_save(game, game.save(a, pair)) as ws:
        first_ping(ws, a)
        if logout:
            assert (
                game.http.delete("/api/sessions/current", headers=a.headers).status_code
                == 204
            )
        else:
            now[0] += timedelta(days=7)
        ws.send_json({"type": "pong", "id": 1})
        assert_close(ws, 4401)


@pytest.mark.parametrize("phase", ["auth", "heartbeat", "pong"])
def test_client_disconnect_finishes_the_asgi_connection_without_waiting_for_deadline(
    open_game, phase
):
    done = Event()
    timing = HEARTBEAT if phase == "pong" else WebSocketTiming()
    game = open_game(timing=timing, finished=done)
    a, _, pair = game.pair()
    with connect_save(game, game.save(a, pair)) as ws:
        if phase == "pong":
            first_ping(ws, a)
        elif phase == "heartbeat":
            authenticate(ws, a)
            assert ws.receive_json()["type"] == "snapshot"
        ws.close()
        # Observe exit before TestClient's context manager can cancel the ASGI app.
        assert done.wait(0.5)


def test_dev_launcher_serves_real_websocket_over_loopback(tmp_path):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    address = f"127.0.0.1:{port}"
    env = {
        **os.environ,
        "TWOWORLDS_STORAGE_BACKEND": "sqlite",
        "TWOWORLDS_SQLITE_PATH": str(tmp_path / "tcp.sqlite"),
        "TWOWORLDS_ALLOWED_ORIGINS": ORIGIN,
        "TWOWORLDS_DEV_PORT": str(port),
    }
    with subprocess.Popen([sys.executable, "-m", "twoworlds.dev"], env=env) as process:
        try:
            with httpx.Client(
                base_url=f"http://{address}", trust_env=False, timeout=1
            ) as http:
                for _ in range(100):
                    try:
                        ok(http.get("/api/scripts"))
                        break
                    except httpx.ConnectError:
                        assert process.poll() is None
                        Event().wait(0.02)
                else:
                    pytest.fail("Loopback development server did not start")
                token = ok(
                    http.post("/api/accounts", json={"display_name": "WebSocket TCP"})
                )["session"]["token"]
            with pytest.raises(InvalidStatus) as denied:
                with connect(
                    f"ws://{address}{URL}", origin="http://not-allowed.test", proxy=None
                ):
                    pytest.fail("Rejected Origin upgraded on TCP")
            assert denied.value.response.status_code == 403
            with connect(
                f"ws://{address}{URL}", origin=ORIGIN, proxy=None, open_timeout=2
            ) as ws:
                ws.send(json.dumps({"type": "auth", "token": token}))
                with pytest.raises(ConnectionClosed) as closed:
                    ws.recv(timeout=2)
                assert closed.value.rcvd.code == 4404
        finally:
            process.terminate()
            process.wait(timeout=5)
