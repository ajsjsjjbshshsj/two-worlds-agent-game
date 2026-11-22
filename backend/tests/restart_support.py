"""Run the real development API as a child process for recovery tests."""

import asyncio
from contextlib import contextmanager
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
from time import monotonic, sleep

import httpx

from tests.contracts.support import Identity, ok
from tests.identity_support import ORIGIN, PASSWORD
from tests.save_support import make_publications
from twoworlds.content.publication import PublicationStore


def until(predicate):
    deadline = monotonic() + 10
    while monotonic() < deadline:
        if result := predicate():
            return result
        sleep(0.02)
    raise AssertionError("Timed out waiting for the recovery test process")


def config(root, backend, mongo=None, *, origin=ORIGIN):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    _, publish = make_publications(root)
    publish()
    publish(identifier="starline")
    env = {
        **os.environ,
        "TWOWORLDS_STORAGE_BACKEND": backend,
        "TWOWORLDS_SQLITE_PATH": str(root / "recovery.sqlite"),
        "TWOWORLDS_DEV_PORT": str(port),
        "TWOWORLDS_ALLOWED_ORIGINS": origin,
        "TWOWORLDS_EMAIL_MODE": "console",
        "TWOWORLDS_COOKIE_SECURE": "0",
    }
    if mongo:
        uri, name = mongo
        env.update(MONGO_URI=uri, MONGO_DATABASE=name)
    return env, f"http://127.0.0.1:{port}"


@contextmanager
def server(root, env, address):
    with (
        (root / "console.log").open("ab") as console,
        subprocess.Popen(
            [sys.executable, "-m", "tests.restart_support", str(root)],
            stdout=console,
            stderr=subprocess.STDOUT,
            env=env,
        ) as process,
        httpx.Client(base_url=address, trust_env=False, timeout=2) as http,
    ):

        def ready():
            assert process.poll() is None
            try:
                return ok(http.get("/api/scripts"))
            except httpx.ConnectError:
                return False

        try:
            until(ready)
            yield process
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def register(http, root, email, name, origin=ORIGIN):
    headers = {"Origin": origin}
    ok(
        http.post(
            "/api/verification-codes",
            headers=headers,
            json={"purpose": "register", "email": email},
        ),
        202,
    )
    pattern = re.compile(rf"to={re.escape(email)} purpose=register code=([0-9]{{6}})")
    code = until(lambda: pattern.search((root / "console.log").read_text("utf-8")))
    response = http.post(
        "/api/accounts",
        headers=headers,
        json={
            "email": email,
            "password": PASSWORD,
            "display_name": name,
            "code": code[1],
        },
    )
    body = ok(response)
    token = response.cookies.get("tw_session")
    assert token and "httponly" in response.headers["set-cookie"].lower()
    return Identity(body["account"]["id"], email, PASSWORD, token)


def stage_clock(game, save, owner, partner):
    for actor, kind, args in [
        (owner, "inspect", {"target": "maintenance_log"}),
        (partner, "inspect", {"target": "sea_chart"}),
        (owner, "set_emitter", {"angle": 0, "pattern": "pulse"}),
        (partner, "set_filter", {"filter": "amber"}),
        (owner, "set_emitter", {"angle": 90, "pattern": "pulse"}),
        (partner, "lock_signal", {}),
        (partner, "route_power", {"target": "tower"}),
        (owner, "inspect", {"target": "clock_gears"}),
    ]:
        save = game.accept(actor, save, kind, args)
    assert save["version"] == 8
    return save


def run_child(root):
    from twoworlds import dev

    factory = dev.create_dev_app

    def create_app():
        app = factory(publication_store=PublicationStore(root / "releases"))

        async def hold_after_commit(scope, receive, send):
            async def intercept(message):
                if (
                    scope.get("method") == "POST"
                    and scope["path"].endswith("/commands")
                    and message["type"] == "http.response.start"
                    and message["status"] == 200
                    and (root / "hold-response").exists()
                ):
                    # The handler returned success after its real database commit.
                    # Hold even the response headers until the parent kills this PID.
                    (root / "committed").touch()
                    await asyncio.Event().wait()
                await send(message)

            await app(scope, receive, intercept)

        return hold_after_commit

    dev.create_dev_app = create_app
    raise SystemExit(dev.main())


if __name__ == "__main__":
    run_child(Path(sys.argv[1]))
