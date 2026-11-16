"""Development wiring only; backend business policies are tested separately."""

import importlib
import subprocess
import sys
import os
import socket
import time

from fastapi.testclient import TestClient
import pytest

from twoworlds.dev import create_dev_app, main


def settings(tmp_path):
    return {
        "TWOWORLDS_STORAGE_BACKEND": "sqlite",
        "TWOWORLDS_SQLITE_PATH": str(tmp_path / "dev.sqlite"),
        "TWOWORLDS_ALLOWED_ORIGINS": "http://127.0.0.1:5173",
    }


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
    ["TWOWORLDS_STORAGE_BACKEND", "TWOWORLDS_SQLITE_PATH", "TWOWORLDS_ALLOWED_ORIGINS"],
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


def test_mongo_never_falls_back_to_sqlite(tmp_path):
    env = {**settings(tmp_path), "TWOWORLDS_STORAGE_BACKEND": "mongo"}
    with pytest.raises(ValueError):
        create_dev_app(env)
    assert not (tmp_path / "dev.sqlite").exists()


def test_sqlite_factory_serves_real_empty_catalog_identity_and_cors(tmp_path):
    app = create_dev_app(settings(tmp_path))
    with TestClient(app) as client:
        result = client.get("/api/scripts")
        assert result.status_code == 200 and result.json() == []
        response = client.post(
            "/api/accounts",
            json={"display_name": "开发测试"},
            headers={"Origin": "http://127.0.0.1:5173"},
        )
        assert response.status_code == 200
        assert response.headers["Cache-Control"] == "no-store"
        assert (
            response.headers["Access-Control-Allow-Origin"] == "http://127.0.0.1:5173"
        )
        assert "Access-Control-Allow-Credentials" not in response.headers
        assert (
            "Access-Control-Allow-Origin"
            not in client.get(
                "/api/scripts", headers={"Origin": "https://unknown.test"}
            ).headers
        )
    with TestClient(create_dev_app(settings(tmp_path))) as reopened:
        token = response.json()["session"]["token"]
        assert (
            reopened.get(
                "/api/me", headers={"Authorization": "Bearer " + token}
            ).status_code
            == 200
        )


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
    with TestClient(create_dev_app(env)) as client:
        response = client.post("/api/accounts", json={"display_name": "Mongo开发验证"})
        assert response.status_code == 200
        assert client.get("/api/scripts").json() == []
        assert (
            client.get(
                "/api/pairs",
                headers={
                    "Authorization": "Bearer " + response.json()["session"]["token"]
                },
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
    process = subprocess.Popen(
        [sys.executable, "-m", "twoworlds.dev"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
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
            created = client.post("/api/accounts", json={"display_name": "真实TCP验证"})
            assert created.status_code == 200
            headers = {"Authorization": "Bearer " + created.json()["session"]["token"]}
            assert client.get("/api/pairs", headers=headers).json() == []
    finally:
        process.terminate()
        output, errors = process.communicate(timeout=10)
    for secret in (created.json()["session"]["token"], created.json()["recovery_key"]):
        assert secret.encode() not in output + errors
