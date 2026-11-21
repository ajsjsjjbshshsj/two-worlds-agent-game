"""Exercise WebSockets through FastAPI and real SQLite/Mongo repositories."""

from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import json
import os
import re
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

from tests.contracts.support import Platform, command, ok
from tests.identity_support import (
    ORIGIN,
    ORIGIN_HEADER,
    PASSWORD,
    RELAXED_POLICIES,
    TEST_SECRET,
    FakeEmailSender,
    request_code,
    unique_email,
)
from tests.save_support import make_publications
from twoworlds.api.app import create_app
from twoworlds.realtime.protocol import WebSocketTiming
from twoworlds.storage.sqlite import SQLiteRepository


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
def open_game(tmp_path, publications, now, request):
    repository_factory = (
        request.getfixturevalue("mongo_repository_factory")
        if getattr(request, "param", "sqlite") == "mongo"
        else lambda: SQLiteRepository(tmp_path / "ws.db")
    )
    with ExitStack() as stack:

        def factory(*, timing=None, finished=None):
            app = create_app(
                repository=repository_factory(),
                email_sender=FakeEmailSender(),
                verification_secret=TEST_SECRET,
                rate_policies=RELAXED_POLICIES,
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
            client.app = app
            return Platform(client, stack.close)

        yield factory


def connect_save(game, save, actor):
    url = URL if save is None else f"/api/ws/saves/{save['id']}"
    return game.http.websocket_connect(url, headers=actor.headers)


def assert_close(ws, code):
    assert ws.receive() == {"type": "websocket.close", "code": code, "reason": ""}


DUAL_STORAGE = pytest.mark.parametrize("open_game", ["sqlite", "mongo"], indirect=True)


@DUAL_STORAGE
def test_exact_origin_and_both_roles_receive_only_the_http_projection(open_game):
    game = open_game()
    a, b, pair = game.pair()
    save = game.save(a, pair)
    save = game.accept(a, save, "inspect", {"target": "maintenance_log"})
    save = game.accept(b, save, "inspect", {"target": "sea_chart"})
    snapshots = {}
    for role, actor, partner in (("a", a, b), ("b", b, a)):
        with connect_save(game, save, actor) as ws:
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
                a.password,
                b.password,
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
    actor = game.account()
    headers = [*headers, ("Cookie", actor.headers["Cookie"])]
    with pytest.raises(WebSocketDisconnect) as rejected:
        with game.http.websocket_connect(URL, headers=httpx.Headers(headers)):
            pytest.fail("Rejected Origin upgraded")
    assert rejected.value.code == 4403


def test_query_credentials_deny_upgrade(open_game):
    game = open_game()
    actor = game.account()
    with pytest.raises(WebSocketDisconnect) as rejected:
        with game.http.websocket_connect(
            f"{URL}?token={actor.token}", headers=actor.headers
        ):
            pytest.fail("Connection with URL credentials upgraded")
    assert rejected.value.code == 4403


@DUAL_STORAGE
@pytest.mark.parametrize(
    "credential",
    [
        "missing",
        "forged",
        "empty",
        "duplicate",
        "split",
        "expired",
        "revoked",
        "bearer",
    ],
)
def test_bad_handshake_credentials_are_rejected_like_http(open_game, now, credential):
    game = open_game()
    a, _, pair = game.pair()
    save = game.save(a, pair)
    cookie = a.headers["Cookie"]
    headers = [("Origin", ORIGIN)]
    if credential == "forged":
        headers.append(("Cookie", "tw_session=" + "tw_session_" + "Z" * 43))
    elif credential == "empty":
        headers.append(("Cookie", "tw_session="))
    elif credential == "duplicate":
        headers.append(("Cookie", f"{cookie}; {cookie}"))
    elif credential == "split":
        headers.extend([("Cookie", cookie), ("Cookie", cookie)])
    elif credential == "bearer":
        headers.append(("Authorization", f"Bearer {a.token}"))
    elif credential in {"expired", "revoked"}:
        headers.append(("Cookie", cookie))
        if credential == "expired":
            now[0] += timedelta(days=7)
        else:
            assert (
                game.http.delete("/api/sessions/current", headers=a.headers).status_code
                == 204
            )
    game.http.cookies.clear()
    headers = httpx.Headers(headers)
    assert game.http.get(f"/api/saves/{save['id']}", headers=headers).status_code == 401
    with pytest.raises(WebSocketDisconnect) as rejected:
        with game.http.websocket_connect(
            f"/api/ws/saves/{save['id']}", headers=headers
        ):
            pytest.fail("Invalid Cookie upgraded")
    assert rejected.value.code == 4401


def test_old_first_frame_cannot_authenticate_without_a_cookie(open_game):
    game = open_game()
    a, _, pair = game.pair()
    save = game.save(a, pair)
    game.http.cookies.clear()
    with pytest.raises(WebSocketDisconnect) as rejected:
        with game.http.websocket_connect(
            f"/api/ws/saves/{save['id']}", headers=ORIGIN_HEADER
        ) as ws:
            ws.send_json({"type": "auth", "token": a.token})
            pytest.fail("Connection upgraded without Cookie")
    assert rejected.value.code == 4401


@pytest.mark.parametrize(
    ("frame", "code"),
    [
        ("{", 4400),
        ("[]", 4400),
        ('{"type":"pong","id":1,"id":1}', 4400),
        ('{"type":"auth"}', 4400),
        ('{"type":"auth","token":true}', 4400),
        ('{"type":"auth","token":"one","token":"two"}', 4400),
        ("[" * 1100 + "]" * 1100, 4400),
        (b'{"type":"auth","token":"ignored"}', 4400),
        ("x" * 4097, 1009),
        ("界" * 1400, 1009),
    ],
)
def test_invalid_pong_frame_closes_without_another_payload(open_game, frame, code):
    game = open_game(timing=HEARTBEAT)
    a, _, pair = game.pair()
    with connect_save(game, game.save(a, pair), a) as ws:
        first_ping(ws)
        if isinstance(frame, bytes):
            ws.send_bytes(frame)
        else:
            ws.send_text(frame)
        assert_close(ws, code)


def test_old_auth_frame_cannot_switch_identity_or_supply_role(open_game):
    game = open_game()
    a, b, pair = game.pair()
    save = game.save(a, pair)
    for extra in ({}, {"role": "a", "account_id": a.account_id, "pair_id": pair["id"]}):
        with connect_save(game, save, a) as ws:
            ws.send_json({"type": "auth", "token": b.token, **extra})
            assert ws.receive_json() == {"type": "snapshot", "save": game.read(a, save)}
            assert_close(ws, 4400)


@DUAL_STORAGE
def test_nonmember_and_missing_save_close_identically(open_game):
    game = open_game()
    a, _, pair = game.pair()
    save = game.save(a, pair)
    outsider = game.account()
    for target, actor in ((save, outsider), (None, a)):
        with connect_save(game, target, actor) as ws:
            assert_close(ws, 4404)


@DUAL_STORAGE
def test_reconnect_reads_a_new_projection_after_an_http_commit(open_game):
    game = open_game()
    a, _, pair = game.pair()
    save = game.save(a, pair)
    with connect_save(game, save, a) as ws:
        assert ws.receive_json() == {"type": "snapshot", "save": save}
    next_save = game.accept(a, save, "inspect", {"target": "maintenance_log"})
    with connect_save(game, save, a) as ws:
        assert ws.receive_json() == {"type": "snapshot", "save": next_save}


@DUAL_STORAGE
def test_revoked_connection_cannot_receive_an_update_before_its_next_ping(open_game):
    game = open_game(
        timing=WebSocketTiming(heartbeat_interval=5, snapshot_interval=0.02)
    )
    a, b, pair = game.pair()
    save = game.save(a, pair)
    with connect_save(game, save, a) as ws:
        assert ws.receive_json() == {"type": "snapshot", "save": save}
        assert (
            game.http.delete("/api/sessions/current", headers=a.headers).status_code
            == 204
        )
        game.accept(b, save, "inspect", {"target": "sea_chart"})
        assert_close(ws, 4401)


def first_ping(ws):
    assert ws.receive_json()["type"] == "snapshot"
    assert ws.receive_json() == {"type": "ping", "id": 1}


def test_matching_pong_keeps_the_same_connection_open(open_game):
    game = open_game(timing=HEARTBEAT)
    a, _, pair = game.pair()
    save = game.save(a, pair)
    with connect_save(game, save, a) as ws:
        first_ping(ws)
        ws.send_json({"type": "pong", "id": 1})
        assert ws.receive_json() == {"type": "ping", "id": 2}
        ws.send_json({"type": "pong", "id": 2})


@pytest.mark.parametrize("bad_id", [2, True, "1"])
def test_pong_must_match_the_outstanding_ping(open_game, bad_id):
    game = open_game(timing=HEARTBEAT)
    a, _, pair = game.pair()
    with connect_save(game, game.save(a, pair), a) as ws:
        first_ping(ws)
        ws.send_json({"type": "pong", "id": bad_id})
        assert_close(ws, 4400)


def test_missing_pong_closes_the_connection(open_game):
    game = open_game(timing=WebSocketTiming(heartbeat_interval=0.02, pong_timeout=0.02))
    a, _, pair = game.pair()
    with connect_save(game, game.save(a, pair), a) as ws:
        first_ping(ws)
        assert_close(ws, 4408)


@DUAL_STORAGE
@pytest.mark.parametrize("logout", [False, True], ids=["expired", "revoked"])
def test_heartbeat_reauthenticates_an_already_verified_connection(
    open_game, now, logout
):
    game = open_game(timing=HEARTBEAT)
    a, _, pair = game.pair()
    with connect_save(game, game.save(a, pair), a) as ws:
        first_ping(ws)
        if logout:
            assert (
                game.http.delete("/api/sessions/current", headers=a.headers).status_code
                == 204
            )
        else:
            now[0] += timedelta(days=7)
        ws.send_json({"type": "pong", "id": 1})
        assert_close(ws, 4401)


@DUAL_STORAGE
def test_password_reset_invalidates_every_old_connection(open_game):
    game = open_game(timing=WebSocketTiming(heartbeat_interval=0.02, pong_timeout=5))
    a, b, pair = game.pair()
    old_login = game.login(a)
    save = game.save(a, pair)
    request_code(game.http, a.email, "reset")
    code = game.http.app.state.email_sender.code_for(a.email, "reset")
    with (
        connect_save(game, save, a) as registration_socket,
        connect_save(game, save, old_login) as login_socket,
        connect_save(game, save, b) as partner_socket,
    ):
        first_ping(registration_socket)
        first_ping(login_socket)
        first_ping(partner_socket)
        reset = game.http.post(
            "/api/password-resets",
            json={"email": a.email, "code": code, "new_password": "new password 123"},
            headers=ORIGIN_HEADER,
        )
        assert reset.status_code == 204, reset.text
        for ws in (registration_socket, login_socket):
            ws.send_json({"type": "pong", "id": 1})
            assert_close(ws, 4401)
        partner_socket.send_json({"type": "pong", "id": 1})
        assert partner_socket.receive_json() == {"type": "ping", "id": 2}
        partner_socket.send_json({"type": "pong", "id": 2})


@pytest.mark.parametrize("phase", ["heartbeat", "pong"])
def test_client_disconnect_finishes_the_asgi_connection_without_waiting_for_deadline(
    open_game, phase
):
    done = Event()
    timing = HEARTBEAT if phase == "pong" else WebSocketTiming()
    game = open_game(timing=timing, finished=done)
    a, _, pair = game.pair()
    with connect_save(game, game.save(a, pair), a) as ws:
        if phase == "pong":
            first_ping(ws)
        else:
            assert ws.receive_json()["type"] == "snapshot"
        ws.close()
        # Observe exit before TestClient's context manager can cancel the ASGI app.
        assert done.wait(0.5)


def register_over_tcp(http, console_path):
    email = unique_email("ws-tcp")
    ok(
        http.post(
            "/api/verification-codes",
            headers=ORIGIN_HEADER,
            json={"email": email, "purpose": "register"},
        ),
        202,
    )
    for _ in range(100):
        match = re.search(
            rf"to={re.escape(email)} purpose=register code=([0-9]{{6}})",
            console_path.read_text(encoding="utf-8"),
        )
        if match:
            break
        Event().wait(0.02)
    else:
        pytest.fail("Development console did not deliver the test code")
    ok(
        http.post(
            "/api/accounts",
            headers=ORIGIN_HEADER,
            json={
                "email": email,
                "code": match[1],
                "password": PASSWORD,
                "display_name": "WS TCP",
            },
        )
    )
    login = http.post(
        "/api/sessions",
        headers=ORIGIN_HEADER,
        json={"email": email, "password": PASSWORD},
    )
    ok(login)
    assert "httponly" in login.headers["set-cookie"].lower()
    token = login.cookies.get("tw_session")
    assert token
    return {"Cookie": f"tw_session={token}"}


def assert_realtime_updates_over_tcp(http, address, a_cookie, pair, save, console_path):
    a_headers = {**a_cookie, **ORIGIN_HEADER}
    b_cookie = register_over_tcp(http, console_path)
    b_headers = {**b_cookie, **ORIGIN_HEADER}
    ok(
        http.post(
            "/api/pairs/join",
            headers=b_headers,
            json={"invite_token": pair["invite_token"]},
        )
    )
    path = f"/api/saves/{save['id']}"
    socket_url = f"ws://{address}/api/ws/saves/{save['id']}"
    with (
        connect(
            socket_url,
            origin=ORIGIN,
            additional_headers=a_cookie,
            proxy=None,
            open_timeout=2,
        ) as a_ws,
        connect(
            socket_url,
            origin=ORIGIN,
            additional_headers=b_cookie,
            proxy=None,
            open_timeout=2,
        ) as b_ws,
    ):
        players = ((a_ws, a_headers, "a"), (b_ws, b_headers, "b"))

        def assert_projections(version):
            views = []
            for ws, headers, role in players:
                message = json.loads(ws.recv(timeout=3))
                projected = ok(http.get(path, headers=headers))
                assert message == {"type": "snapshot", "save": projected}
                assert projected["version"] == version and projected["role"] == role
                views.append(projected["personal"])
            assert views[0]["devices"].keys().isdisjoint(views[1]["devices"])
            return views

        assert_projections(0)
        for headers, target in (
            (a_headers, "maintenance_log"),
            (b_headers, "sea_chart"),
        ):
            payload = command(save, "inspect", {"target": target})
            save = ok(http.post(f"{path}/commands", headers=headers, json=payload))[
                "save"
            ]
            a_view, b_view = assert_projections(save["version"])
        assert a_view["clues"] and b_view["clues"]
        assert all(clue not in b_view["clues"] for clue in a_view["clues"])
        assert all(clue not in a_view["clues"] for clue in b_view["clues"])

        private_question = "only A can see this demo turn"
        payload = command(save, "talk", {"question": private_question})
        advanced = ok(http.post(f"{path}/commands", headers=a_headers, json=payload))
        a_view, b_view = assert_projections(advanced["save"]["version"])
        assert a_view["dialogue"][0]["question"] == private_question
        assert b_view["dialogue"] == []
        duplicate = ok(http.post(f"{path}/commands", headers=a_headers, json=payload))
        assert duplicate["receipt"]["duplicate"] is True
        for ws, headers, _ in players:
            with pytest.raises(TimeoutError):
                ws.recv(timeout=0.65)
            assert (
                ok(http.get(path, headers=headers))["version"]
                == advanced["save"]["version"]
            )


@pytest.mark.parametrize("backend", ["sqlite", "mongo"])
def test_dev_launcher_serves_real_websocket_over_loopback(tmp_path, request, backend):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    address = f"127.0.0.1:{port}"
    env = {
        **os.environ,
        "TWOWORLDS_STORAGE_BACKEND": backend,
        "TWOWORLDS_SQLITE_PATH": str(tmp_path / "tcp.sqlite"),
        "TWOWORLDS_ALLOWED_ORIGINS": ORIGIN,
        "TWOWORLDS_DEV_PORT": str(port),
        "TWOWORLDS_EMAIL_MODE": "console",
        "TWOWORLDS_COOKIE_SECURE": "0",
    }
    if backend == "mongo":
        db, uri = request.getfixturevalue("mongo_database")
        env.update(MONGO_URI=uri, MONGO_DATABASE=db.name)
    # Invoke the real launcher in a subprocess with an isolated test publication.
    launcher = """
import sys
from pathlib import Path
from tests.save_support import make_publications
from twoworlds import dev

store, publish = make_publications(Path(sys.argv[1]))
publish()
factory = dev.create_dev_app
dev.create_dev_app = lambda: factory(publication_store=store)
raise SystemExit(dev.main())
"""
    console_path = tmp_path / "console.log"
    with (
        console_path.open("wb") as console,
        subprocess.Popen(
            [sys.executable, "-c", launcher, str(tmp_path / "publications")],
            env=env,
            stdout=console,
        ) as process,
    ):
        try:
            with httpx.Client(
                base_url=f"http://{address}", trust_env=False, timeout=2
            ) as http:
                for _ in range(200):
                    try:
                        ok(http.get("/api/scripts"))
                        break
                    except httpx.ConnectError:
                        assert process.poll() is None
                        Event().wait(0.02)
                else:
                    pytest.fail("Loopback development server did not start")
                cookie = register_over_tcp(http, console_path)
                headers = {**cookie, **ORIGIN_HEADER}
                pair = ok(http.post("/api/pairs", headers=headers))
                save = ok(
                    http.post(
                        "/api/saves",
                        headers=headers,
                        json={
                            "pair_id": pair["id"],
                            "script_id": "lighthouse",
                            "script_version": "1.0.0",
                        },
                    )
                )
                path = f"/api/ws/saves/{save['id']}"
                projection = ok(http.get(f"/api/saves/{save['id']}", headers=headers))

            for origin, cookies in (("http://not-allowed.test", cookie), (ORIGIN, {})):
                with pytest.raises(InvalidStatus) as denied:
                    with connect(
                        f"ws://{address}{path}",
                        origin=origin,
                        additional_headers=cookies,
                        proxy=None,
                        open_timeout=2,
                    ):
                        pytest.fail("Invalid Origin or absent Cookie upgraded on TCP")
                assert denied.value.response.status_code == 403
            with connect(
                f"ws://{address}{path}",
                origin=ORIGIN,
                additional_headers=cookie,
                proxy=None,
                open_timeout=2,
            ) as ws:
                assert json.loads(ws.recv(timeout=2)) == {
                    "type": "snapshot",
                    "save": projection,
                }
            with connect(
                f"ws://{address}{URL}",
                origin=ORIGIN,
                additional_headers=cookie,
                proxy=None,
                open_timeout=2,
            ) as ws:
                with pytest.raises(ConnectionClosed) as closed:
                    ws.recv(timeout=2)
                assert closed.value.rcvd.code == 4404
            with httpx.Client(
                base_url=f"http://{address}", trust_env=False, timeout=3
            ) as http:
                assert_realtime_updates_over_tcp(
                    http, address, cookie, pair, save, console_path
                )
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
