"""Development wiring only; backend business policies are tested separately."""

import importlib
import re
import subprocess
import sys
import os
import socket
import time

from fastapi.testclient import TestClient
import pytest

from tests.identity_support import PASSWORD, auth, unique_email
from twoworlds.dev import create_dev_app, main

DEV_ORIGIN = "http://127.0.0.1:5173"


def settings(tmp_path):
    return {
        "TWOWORLDS_STORAGE_BACKEND": "sqlite",
        "TWOWORLDS_SQLITE_PATH": str(tmp_path / "dev.sqlite"),
        "TWOWORLDS_ALLOWED_ORIGINS": DEV_ORIGIN,
        "TWOWORLDS_EMAIL_MODE": "console",
    }


def register_via_console(client, email):
    """Dev flow: request a code, read it from the dev console, then register."""
    import io
    from contextlib import redirect_stdout

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        response = client.post(
            "/api/verification-codes",
            json={"email": email, "purpose": "register"},
            headers={"Origin": DEV_ORIGIN},
        )
    assert response.status_code == 202
    printed = buffer.getvalue()
    match = re.search(r"\[dev-email\] to=(\S+) purpose=register code=(\d{6})", printed)
    assert match and match.group(1) == email
    response = client.post(
        "/api/accounts",
        json={
            "email": email,
            "code": match.group(2),
            "password": PASSWORD,
            "display_name": "开发测试",
        },
        headers={"Origin": DEV_ORIGIN},
    )
    assert response.status_code == 200, response.text
    return response


def test_import_has_no_app_or_database(tmp_path):
    module = importlib.import_module("twoworlds.dev")
    assert not hasattr(module, "app")
    result = subprocess.run(
        [sys.executable, "-c", "import twoworlds.dev; print('import-only')"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "import-only"
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "missing",
    [
        "TWOWORLDS_STORAGE_BACKEND",
        "TWOWORLDS_SQLITE_PATH",
        "TWOWORLDS_ALLOWED_ORIGINS",
        "TWOWORLDS_EMAIL_MODE",
    ],
)
def test_explicit_configuration_required(tmp_path, missing):
    env = settings(tmp_path)
    del env[missing]
    with pytest.raises(ValueError):
        create_dev_app(env)
    assert not (tmp_path / "dev.sqlite").exists()


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        "http://127.0.0.1:5173/",
        "https://user:SECRET@example.test",
        "https://example.test?token=SECRET",
    ],
)
def test_rejects_unsafe_origins_before_connecting(tmp_path, origin):
    env = {**settings(tmp_path), "TWOWORLDS_ALLOWED_ORIGINS": origin}
    with pytest.raises(ValueError) as error:
        create_dev_app(env)
    assert "SECRET" not in str(error.value)
    assert not (tmp_path / "dev.sqlite").exists()


def test_email_mode_must_be_explicit_and_smtp_never_leaks_credentials(tmp_path):
    env = {**settings(tmp_path), "TWOWORLDS_EMAIL_MODE": "auto"}
    with pytest.raises(ValueError):
        create_dev_app(env)
    env = {
        **settings(tmp_path),
        "TWOWORLDS_EMAIL_MODE": "smtp",
        "SMTP_HOST": "smtp.example.test",
        "SMTP_FROM": "noreply@example.test",
        "SMTP_USERNAME": "mailer",
        "SMTP_PASSWORD": "SECRET_SMTP_PASSWORD",
    }
    del env["SMTP_HOST"]
    with pytest.raises(ValueError) as error:
        create_dev_app(env)
    assert "SECRET_SMTP_PASSWORD" not in str(error.value)
    assert not (tmp_path / "dev.sqlite").exists()


def test_mongo_never_falls_back_to_sqlite(tmp_path):
    env = {**settings(tmp_path), "TWOWORLDS_STORAGE_BACKEND": "mongo"}
    with pytest.raises(ValueError):
        create_dev_app(env)
    assert not (tmp_path / "dev.sqlite").exists()


def test_sqlite_factory_serves_real_catalog_and_cookie_identity(tmp_path):
    app = create_dev_app(settings(tmp_path))
    email = unique_email("dev")
    with TestClient(app) as client:
        result = client.get("/api/scripts")
        assert result.status_code == 200 and result.json() == []
        response = register_via_console(client, email)
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["Access-Control-Allow-Origin"] == DEV_ORIGIN
        assert "tw_session=" in response.headers["Set-Cookie"]
        assert "HttpOnly" in response.headers["Set-Cookie"]
        assert (
            "Access-Control-Allow-Origin"
            not in client.get(
                "/api/scripts", headers={"Origin": "https://unknown.test"}
            ).headers
        )
        token = response.cookies.get("tw_session")
        assert client.get("/api/me", headers=auth({"token": token})).status_code == 200
    # A restarted process keeps accounts; login works without any new code.
    with TestClient(create_dev_app(settings(tmp_path))) as reopened:
        again = reopened.post(
            "/api/sessions",
            json={"email": email, "password": PASSWORD},
            headers={"Origin": DEV_ORIGIN},
        )
        assert again.status_code == 200
        assert (
            reopened.get(
                "/api/me", headers=auth({"token": again.cookies.get("tw_session")})
            ).status_code
            == 200
        )


def test_explicit_verification_secret_survives_restart(tmp_path):
    import io
    from contextlib import redirect_stdout

    secret = "dev-verification-secret-0123456789abcdef"
    env = {**settings(tmp_path), "TWOWORLDS_VERIFICATION_SECRET": secret}
    email = unique_email("restart")
    buffer = io.StringIO()
    with TestClient(create_dev_app(env)) as first:
        with redirect_stdout(buffer):
            assert (
                first.post(
                    "/api/verification-codes",
                    json={"email": email, "purpose": "register"},
                    headers={"Origin": DEV_ORIGIN},
                ).status_code
                == 202
            )
    match = re.search(r"code=(\d{6})", buffer.getvalue())
    assert match
    # Same injected secret: the outstanding code stays usable after restart,
    # without requesting a new one (a resend would kill the old code).
    with TestClient(create_dev_app(env)) as second:
        response = second.post(
            "/api/accounts",
            json={
                "email": email,
                "code": match.group(1),
                "password": PASSWORD,
                "display_name": "重启验证",
            },
            headers={"Origin": DEV_ORIGIN},
        )
        assert response.status_code == 200, response.text
        assert secret not in response.text


def test_main_restricts_listener_and_disables_sensitive_logging(tmp_path, monkeypatch):
    import uvicorn

    seen = {}
    for key, value in settings(tmp_path).items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: seen.update(kwargs))
    assert main() == 0
    assert seen["host"] == "127.0.0.1"
    assert seen["access_log"] is False
    assert seen["proxy_headers"] is False
    assert seen["log_level"] == "critical"


def test_startup_error_does_not_echo_configuration(monkeypatch, capsys):
    monkeypatch.setenv("TWOWORLDS_STORAGE_BACKEND", "SECRET_URI_PASSWORD")
    assert main() == 1
    captured = capsys.readouterr()
    assert "SECRET" not in captured.out + captured.err


def test_mongo_factory_uses_real_database_without_sqlite_fallback(
    tmp_path, mongo_database
):
    database, uri = mongo_database
    env = {
        **settings(tmp_path),
        "TWOWORLDS_STORAGE_BACKEND": "mongo",
        "MONGO_URI": uri,
        "MONGO_DATABASE": database.name,
    }
    app = create_dev_app(env)
    email = unique_email("mongo-dev")
    with TestClient(app) as client:
        response = register_via_console(client, email)
        assert client.get("/api/scripts").json() == []
        token = response.cookies.get("tw_session")
        assert (
            client.get(
                "/api/pairs",
                headers=auth({"token": token}),
            ).json()
            == []
        )
    assert database.accounts.count_documents({}) == 1
    assert not (tmp_path / "dev.sqlite").exists()


def test_test_only_publications_are_explicitly_injected_not_formally_published(
    tmp_path, published_story
):
    store, publish = published_story
    publish()
    with TestClient(
        create_dev_app(settings(tmp_path), publication_store=store)
    ) as client:
        assert client.get("/api/scripts").json()[0]["id"] == "lighthouse"
    with TestClient(create_dev_app(settings(tmp_path))) as client:
        assert client.get("/api/scripts").json() == []


@pytest.mark.parametrize("backend", ["sqlite", "mongo"])
def test_real_cli_tcp_startup(tmp_path, request, backend):
    import httpx

    env = {**os.environ, **settings(tmp_path)}
    if backend == "mongo":
        database, uri = request.getfixturevalue("mongo_database")
        env.update(
            TWOWORLDS_STORAGE_BACKEND="mongo",
            MONGO_URI=uri,
            MONGO_DATABASE=database.name,
        )
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    env["TWOWORLDS_DEV_PORT"] = str(port)
    # Console codes go to a file: a PIPE could fill and block the server.
    console = open(tmp_path / "console.log", "w+b")
    process = subprocess.Popen(
        [sys.executable, "-m", "twoworlds.dev"],
        env=env,
        stdout=console,
        stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    email = unique_email("tcp")
    try:
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=1
        ) as client:
            for _ in range(100):
                try:
                    result = client.get("/api/scripts")
                    break
                except httpx.TransportError:
                    assert process.poll() is None, (
                        "Development server exited before serving"
                    )
                    time.sleep(0.1)
            else:
                pytest.fail("Development TCP listener did not start")
            assert result.status_code == 200 and result.json() == []
            requested = client.post(
                "/api/verification-codes",
                json={"email": email, "purpose": "register"},
                headers={"Origin": DEV_ORIGIN},
            )
            assert requested.status_code == 202
            console.flush()
            printed = (tmp_path / "console.log").read_text(encoding="utf-8")
            match = re.search(
                rf"\[dev-email\] to={re.escape(email)} purpose=register code=(\d{{6}})",
                printed,
            )
            assert match, printed
            created = client.post(
                "/api/accounts",
                json={
                    "email": email,
                    "code": match.group(1),
                    "password": PASSWORD,
                    "display_name": "真实TCP验证",
                },
                headers={"Origin": DEV_ORIGIN},
            )
            assert created.status_code == 200, created.text
            token = created.cookies.get("tw_session")
            assert token
            assert client.get("/api/pairs", headers=auth({"token": token})).json() == []
    finally:
        process.terminate()
        _, errors = process.communicate(timeout=10)
        console.close()
    output = (tmp_path / "console.log").read_bytes() + errors
    # The dev console intentionally shows the code; passwords and session
    # tokens must never appear in any process output.
    assert PASSWORD.encode() not in output
    assert token.encode() not in output
