"""Opt-in HTTPS/WSS smoke against a disposable loopback Compose project."""

import argparse
from contextlib import ExitStack
from io import BytesIO
import json
import os
from pathlib import Path
import ssl
import subprocess
import tarfile
from tempfile import TemporaryDirectory
from time import monotonic, sleep
from uuid import uuid4

import httpx
from websockets.exceptions import ConnectionClosed, InvalidStatus
from websockets.sync.client import connect

from tests.save_support import make_publications

ROOT = Path(__file__).resolve().parents[2]
ORIGIN = "https://localhost"
PASSWORD = "fixture-local-only-password"
API_KEY = "unused-npc-key-smoke-fixture"
SMTP_PASSWORD = "unused-smtp-password-smoke-fixture"
QUESTION = "private-player-question-smoke-fixture"
REJECTED_QUERY = "discarded-wss-query-smoke-fixture"


def run(*args, **kwargs):
    return subprocess.run(args, check=True, cwd=ROOT, capture_output=True, **kwargs)


def expect_unauthorized_socket(address, tls, *, origin=ORIGIN, cookie=None):
    try:
        with connect(
            address,
            ssl=tls,
            origin=origin,
            additional_headers={"Cookie": cookie} if cookie else None,
            proxy=None,
        ):
            raise AssertionError("Unexpected WebSocket Upgrade")
    except InvalidStatus as error:
        assert error.response.status_code == 403


def command(client, save, kind, args, version):
    result = client.post(
        save + "/commands",
        json={
            "kind": kind,
            "args": args,
            "expected_version": version,
            "request_id": str(uuid4()),
        },
    )
    result.raise_for_status()
    return result.json()["save"]


def system_probe(compose, route):
    result = compose(
        "exec",
        "-T",
        "backend",
        "python",
        "-c",
        """
import sys
from urllib.error import HTTPError
from urllib.request import build_opener, ProxyHandler
opener = build_opener(ProxyHandler({}))
try:
    reply = opener.open("http://127.0.0.1:8000/health/" + sys.argv[1], timeout=4)
except HTTPError as exc:
    reply = exc
with reply:
    print(reply.status, reply.read().decode())
""",
        route,
    )
    status, body = result.stdout.decode().split(" ", 1)
    return int(status), json.loads(body)


def wait_until(get, expected):
    end = monotonic() + 40
    while monotonic() < end:
        try:
            if get() == expected:
                return
        except (subprocess.CalledProcessError, httpx.TransportError):
            pass
        sleep(0.5)
    raise AssertionError(f"Service did not converge to {expected!r}")


def check_images(compose):
    bundle = compose(
        "exec", "-T", "frontend", "tar", "cf", "-", "-C", "/usr/share/nginx/html", "."
    ).stdout
    with tarfile.open(fileobj=BytesIO(bundle)) as artifact:
        contents = {
            m.name: artifact.extractfile(m).read() for m in artifact if m.isfile()
        }
    assert any(name.endswith(".js") for name in contents)
    assert not any(name.endswith((".map", ".env")) for name in contents)
    for item in contents.values():
        for marker in (
            API_KEY,
            SMTP_PASSWORD,
            "http://localhost:8000",
            "a_maintenance_log",
            "b_sea_chart",
        ):
            assert marker.encode() not in item


def smoke(compose, tls):
    # Seed synthetic test accounts directly so this suite never requests email.
    compose(
        "exec",
        "-T",
        "backend",
        "python",
        "-c",
        """
import os
import sys
from twoworlds.application.identity import IdentityService
from twoworlds.storage.mongo import MongoRepository
repository = MongoRepository(os.environ["MONGO_URI"], os.environ["MONGO_DATABASE"])
try:
    identity = IdentityService(repository)
    for role in ("alpha", "bravo"):
        identity.register(role + "@example.invalid", sys.argv[1], role)
finally:
    repository.close()
""",
        PASSWORD,
    )
    with ExitStack() as stack:
        a, b = [
            stack.enter_context(
                httpx.Client(
                    base_url=ORIGIN,
                    verify=tls,
                    trust_env=False,
                    headers={"Origin": ORIGIN},
                    timeout=8,
                )
            )
            for _ in range(2)
        ]
        redirect = stack.enter_context(httpx.Client(trust_env=False)).get(
            "http://localhost/?check=1"
        )
        assert (
            redirect.status_code == 308
            and redirect.headers["location"] == ORIGIN + "/?check=1"
        )
        assert a.get("/", headers={"Host": "example.invalid"}).status_code == 421
        homepage = a.get("/")
        assert homepage.status_code == 200
        assert "max-age=" in homepage.headers["strict-transport-security"]
        assert homepage.headers["x-content-type-options"] == "nosniff"
        assert "no-store" in a.get("/sw.js").headers["cache-control"]
        assert a.get("/health/ready").status_code == 404
        for path in ("/api", "/api/unknown"):
            result = a.get(path)
            assert (
                result.status_code == 404
                and result.json()["error"]["code"] == "NOT_FOUND"
            )
        assert a.get("/api/me").status_code == 401
        assert a.post("/api/sessions", content=b" " * 16385).status_code == 413
        print(
            "PASS HTTPS redirect, Host handling, private probes, PWA headers and API 4xx"
        )

        spoof = {
            "Origin": "https://example.invalid",
            "X-Forwarded-Proto": "https",
            "X-Forwarded-Host": "localhost",
            "Forwarded": "host=localhost;proto=https",
        }
        denied = a.post("/api/sessions", headers=spoof, json={})
        assert (
            denied.status_code == 403
            and denied.json()["error"]["code"] == "CSRF_REJECTED"
        )
        assert "access-control-allow-origin" not in denied.headers
        for role, client in (("alpha", a), ("bravo", b)):
            response = client.post(
                "/api/sessions",
                json={"email": role + "@example.invalid", "password": PASSWORD},
            )
            response.raise_for_status()
            assert response.headers["access-control-allow-origin"] == ORIGIN
            cookie = response.headers["set-cookie"].lower()
            assert all(
                flag in cookie for flag in ("secure", "httponly", "samesite=lax")
            )
            assert client.get("/api/me").status_code == 200
        tokens = [client.cookies["tw_session"] for client in (a, b)]
        cookies = [f"tw_session={token}" for token in tokens]
        pair_response = a.post("/api/pairs")
        pair_response.raise_for_status()
        pair = pair_response.json()
        b.post(
            "/api/pairs/join", json={"invite_token": pair["invite_token"]}
        ).raise_for_status()
        response = a.post(
            "/api/saves",
            json={
                "pair_id": pair["id"],
                "script_id": "lighthouse",
                "script_version": "1.0.0",
            },
        )
        response.raise_for_status()
        save_id = response.json()["id"]
        addr = f"wss://localhost/api/ws/saves/{save_id}"
        save = f"/api/saves/{save_id}"
        expect_unauthorized_socket(addr, tls)
        expect_unauthorized_socket(
            addr, tls, origin="http://localhost", cookie=cookies[0]
        )
        expect_unauthorized_socket(addr, tls, origin=None, cookie=cookies[0])
        expect_unauthorized_socket(
            f"{addr}?token={REJECTED_QUERY}", tls, cookie=cookies[0]
        )

        def open_socket(cookie):
            return connect(
                addr,
                ssl=tls,
                origin=ORIGIN,
                additional_headers={"Cookie": cookie},
                proxy=None,
            )

        def snapshot(ws, client):
            message = json.loads(ws.recv(timeout=6))
            assert message["type"] == "snapshot"
            view = client.get(save)
            view.raise_for_status()
            assert view.json() == message["save"]
            return message["save"]

        with open_socket(cookies[0]) as ws_a, open_socket(cookies[1]) as ws_b:
            assert snapshot(ws_a, a)["role"] == "a"
            assert snapshot(ws_b, b)["role"] == "b"
            command(a, save, "inspect", {"target": "maintenance_log"}, 0)
            assert snapshot(ws_a, a)["version"] == 1
            view_b = snapshot(ws_b, b)
            assert view_b["version"] == 1 and view_b["personal"]["clues"] == []
        command(b, save, "inspect", {"target": "sea_chart"}, 1)
        command(a, save, "talk", {"question": QUESTION}, 2)
        with open_socket(cookies[0]) as ws_a, open_socket(cookies[1]) as ws_b:
            view_a, view_b = snapshot(ws_a, a), snapshot(ws_b, b)
            assert view_a["version"] == view_b["version"] == 3
            assert [x["id"] for x in view_a["personal"]["clues"]] == [
                "a_maintenance_log"
            ]
            assert [x["id"] for x in view_b["personal"]["clues"]] == ["b_sea_chart"]
            assert view_a["personal"]["dialogue"][0]["question"] == QUESTION
            assert not view_b["personal"]["dialogue"]
            ws_b.send("x" * 4097)
            try:
                ws_b.recv(timeout=6)
                raise AssertionError("Oversized frame accepted")
            except ConnectionClosed as error:
                assert error.rcvd.code == 1009
            assert json.loads(ws_a.recv(timeout=12))["type"] == "ping"
            try:
                ws_a.recv(timeout=7)
                raise AssertionError("Missing pong was accepted")
            except ConnectionClosed as error:
                assert error.rcvd.code == 4408
        print(
            "PASS Secure session, exact CORS/Origin, WSS Upgrade, role projections, reconnect, 1009 and 4408"
        )

        assert system_probe(compose, "live") == (200, {"status": "ok"})
        assert system_probe(compose, "ready") == (200, {"status": "ok"})
        compose("stop", "mongo")
        assert system_probe(compose, "live") == (200, {"status": "ok"})
        assert system_probe(compose, "ready") == (503, {"status": "unavailable"})
        backend_id = compose("ps", "-q", "backend").stdout.decode().strip()

        def health_status():
            return (
                run(
                    "docker",
                    "inspect",
                    "--format",
                    "{{.State.Running}} {{.State.Health.Status}}",
                    backend_id,
                )
                .stdout.decode()
                .strip()
            )

        wait_until(health_status, "true unhealthy")
        unavailable = a.get("/api/me")
        assert (
            unavailable.status_code == 503
            and unavailable.json()["error"]["code"] == "DEPENDENCY_UNAVAILABLE"
        )
        compose("start", "mongo")
        wait_until(lambda: system_probe(compose, "ready"), (200, {"status": "ok"}))
        assert a.get("/api/me").status_code == 200
        wait_until(health_status, "true healthy")
        check_images(compose)
        compose("stop", "backend")
        bad_gateway = a.get("/api/me?marker=" + REJECTED_QUERY)
        assert bad_gateway.status_code in {502, 504}, bad_gateway.status_code
        assert REJECTED_QUERY not in bad_gateway.text
        logs = compose("logs", "--no-color", "backend", "gateway", "frontend")
        output = logs.stdout + logs.stderr
        for secret in (
            API_KEY,
            SMTP_PASSWORD,
            PASSWORD,
            QUESTION,
            REJECTED_QUERY,
            pair["invite_token"],
            *tokens,
        ):
            assert secret.encode() not in output
        assert b"WebSocket handshake status=403" in output
        print(
            f"PASS real MongoDB outage and recovery, gateway {bad_gateway.status_code}, "
            "production bundle and log privacy"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prebuilt", nargs=2, metavar=("BACKEND_IMAGE", "FRONTEND_IMAGE")
    )
    args = parser.parse_args()
    with TemporaryDirectory(prefix="tw-https-smoke-") as folder:
        root = Path(folder)
        _, publish = make_publications(root)
        publish()
        # The production container reads the synthetic mount as UID 10001.
        for asset in (root / "releases", *(root / "releases").rglob("*")):
            asset.chmod(0o755 if asset.is_dir() else 0o644)
        run(
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-sha256",
            "-nodes",
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=DNS:localhost",
            "-keyout",
            str(root / "privkey.pem"),
            "-out",
            str(root / "fullchain.pem"),
        )
        tls = ssl.create_default_context(cafile=str(root / "fullchain.pem"))
        overlay = root / "compose.json"
        services = {
            "backend": {
                "volumes": [
                    {
                        "type": "bind",
                        "source": str(root / "releases"),
                        "read_only": True,
                        "target": "/app/.venv/lib/python3.12/site-packages/twoworlds/content/published",
                    }
                ]
            }
        }
        if args.prebuilt:
            services["backend"]["image"], frontend = args.prebuilt
            services["frontend"] = {"image": frontend}
        overlay.write_text(json.dumps({"services": services}))
        project = "tw-https-" + uuid4().hex[:8]
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith(("TWOWORLDS_", "MONGO_", "SMTP_", "COMPOSE_", "VITE_"))
        }
        env.update(
            TWOWORLDS_PUBLIC_HOST="localhost",
            TWOWORLDS_BIND_IP="127.0.0.1",
            TWOWORLDS_TLS_DIR=str(root),
            TWOWORLDS_VERIFICATION_SECRET=uuid4().hex,
            TWOWORLDS_AI_MODE="demo",
            TWOWORLDS_AI_API_KEY=API_KEY,
            SMTP_HOST="mail.example.invalid",
            SMTP_FROM="sender@example.invalid",
            SMTP_USERNAME="fixture",
            SMTP_PASSWORD=SMTP_PASSWORD,
        )

        def compose(*command):
            return run(
                "docker",
                "compose",
                "--env-file",
                os.devnull,
                "-p",
                project,
                "-f",
                "compose.yml",
                "-f",
                str(overlay),
                *command,
                env=env,
            )

        # Check that the real configuration publishes only the loopback gateway.
        config = json.loads(compose("config", "--format", "json").stdout)
        services = config["services"]
        assert services["backend"]["environment"]["TWOWORLDS_AI_API_KEY"] == API_KEY
        assert services["frontend"]["build"]["args"]["VITE_API_BASE_URL"] == ""
        assert all(
            API_KEY not in json.dumps(service)
            for name, service in services.items()
            if name != "backend"
        )
        assert {name for name, data in services.items() if data.get("ports")} == {
            "gateway"
        }
        assert all(
            port["host_ip"] == "127.0.0.1" for port in services["gateway"]["ports"]
        )
        try:
            compose("up", "-d", "--no-build" if args.prebuilt else "--build", "--wait")
            compose("exec", "-T", "gateway", "nginx", "-t")
            try:
                compose("run", "--rm", "--no-deps", "-e", "SMTP_HOST=", "backend")
                raise AssertionError("Missing SMTP_HOST must prevent startup")
            except subprocess.CalledProcessError as error:
                assert (
                    error.returncode == 1
                    and b"Explicit SMTP host, port and from address required"
                    in error.stderr
                )
                assert SMTP_PASSWORD.encode() not in error.stderr + error.stdout
            smoke(compose, tls)
        except subprocess.CalledProcessError as error:
            print(
                compose(
                    "logs", "--no-color", "--tail=25", "backend", "gateway", "frontend"
                ).stdout.decode(errors="replace")
            )
            raise SystemExit(error.stderr.decode(errors="replace")) from None
        finally:
            compose("down", "-v")


if __name__ == "__main__":
    main()
