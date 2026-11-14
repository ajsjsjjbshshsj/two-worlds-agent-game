from datetime import timedelta
import logging

from fastapi.testclient import TestClient
import pytest


def account(client):
    response = client.post("/api/accounts", json={"display_name": "旅人"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    return response.json()


def bearer(token):
    return {"Authorization": "Bearer " + token}


def error(response, status, code):
    assert response.status_code == status
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "retryable"}
    assert body["error"]["code"] == code
    assert type(body["error"]["retryable"]) is bool


def test_shapes_digest_storage_and_logs(clients, caplog):
    caplog.set_level(logging.INFO)
    client, _, repo = clients()
    created = account(client)
    assert set(created) == {"account", "recovery_key", "session"}
    assert set(created["account"]) == {"id", "display_name"}
    assert set(created["session"]) == {"token", "expires_at"}
    assert created["recovery_key"] != created["session"]["token"]
    stored = repo.get_account(created["account"]["id"])
    me = client.get("/api/me", headers=bearer(created["session"]["token"]))
    assert me.json() == {
        "account": created["account"],
        "session": {"expires_at": created["session"]["expires_at"]},
    }
    assert me.headers["cache-control"] == "no-store"
    restored = client.post(
        "/api/sessions/recover", json={"recovery_key": created["recovery_key"]}
    )
    assert restored.status_code == 200
    assert set(restored.json()) == {"account", "session"}
    assert restored.json()["account"] == created["account"]
    new_token = restored.json()["session"]["token"]
    assert new_token != created["session"]["token"]
    assert (
        client.get("/api/me", headers=bearer(created["session"]["token"])).status_code
        == 200
    )
    for secret in (created["recovery_key"], created["session"]["token"], new_token):
        assert secret not in caplog.text
        assert secret not in repo.get_account(stored.id).model_dump_json()
    for digest in (stored.recovery_digest, stored.sessions[0].token_digest):
        assert digest not in me.text + restored.text + caplog.text


@pytest.mark.parametrize(
    "field", ["account_id", "player_id", "role", "recovery_key", "user_id"]
)
def test_extra_fields_and_validation_do_not_echo_inputs(clients, field):
    client, _, _ = clients()
    marker = "private-input-do-not-echo"
    response = client.post(
        "/api/accounts", json={"display_name": "旅人", field: marker}
    )
    error(response, 422, "INVALID_INPUT")
    assert marker not in response.text


@pytest.mark.parametrize(
    "body",
    [{}, {"display_name": 42}, {"display_name": " "}, {"display_name": "x" * 41}],
)
def test_create_schema_invalid(clients, body):
    client, _, _ = clients()
    error(client.post("/api/accounts", json=body), 422, "INVALID_INPUT")


def test_auth_rejections_logout_and_other_device(clients):
    client, _, repo = clients()
    created = account(client)
    restored = client.post(
        "/api/sessions/recover", json={"recovery_key": created["recovery_key"]}
    ).json()
    token = created["session"]["token"]
    for headers in (
        {},
        {"Authorization": "Basic secret"},
        {"Authorization": "Bearer"},
        bearer("bad"),
        bearer(created["recovery_key"]),
        bearer(created["account"]["id"]),
    ):
        error(client.get("/api/me", headers=headers), 401, "UNAUTHENTICATED")
    error(client.get("/api/me", params={"token": token}), 401, "UNAUTHENTICATED")
    response = client.delete("/api/sessions/current", headers=bearer(token))
    assert response.status_code == 204 and response.content == b""
    assert response.headers["cache-control"] == "no-store"
    error(client.get("/api/me", headers=bearer(token)), 401, "UNAUTHENTICATED")
    error(
        client.delete("/api/sessions/current", headers=bearer(token)),
        401,
        "UNAUTHENTICATED",
    )
    assert (
        client.get("/api/me", headers=bearer(restored["session"]["token"])).status_code
        == 200
    )
    assert repo.get_account(created["account"]["id"]) is not None


def test_expiry_eviction_and_clock_error_http(clients, clocks):
    clock, rate = clocks
    client, _, _ = clients(identity_clock=lambda: clock[0], rate_clock=lambda: rate[0])
    created = account(client)
    tokens = [created["session"]["token"]]
    start = clock[0]
    for _ in range(5):
        clock[0] += timedelta(seconds=1)
        tokens.append(
            client.post(
                "/api/sessions/recover", json={"recovery_key": created["recovery_key"]}
            ).json()["session"]["token"]
        )
    error(client.get("/api/me", headers=bearer(tokens[0])), 401, "UNAUTHENTICATED")
    clock[0] = start + timedelta(seconds=4)
    error(client.get("/api/me", headers=bearer(tokens[1])), 503, "CLOCK_ERROR")
    clock[0] = start + timedelta(seconds=5, days=7)
    error(client.get("/api/me", headers=bearer(tokens[-1])), 401, "UNAUTHENTICATED")


@pytest.mark.parametrize(
    "body,status,code",
    [
        ({"recovery_key": "wrong"}, 401, "UNAUTHENTICATED"),
        ({"account_id": "someone"}, 422, "INVALID_INPUT"),
        ({"recovery_key": "x" * 129}, 422, "INVALID_INPUT"),
    ],
)
def test_recover_errors(clients, body, status, code):
    client, _, _ = clients()
    error(client.post("/api/sessions/recover", json=body), status, code)


def test_dependency_failure_and_unknown_exception_safe(clients):
    client, app, repo = clients()
    created = account(client)
    repo.close()
    error(
        client.get("/api/me", headers=bearer(created["session"]["token"])),
        503,
        "DEPENDENCY_UNAVAILABLE",
    )

    @app.get("/test-private-error")
    def broken():
        raise RuntimeError("private-error-must-not-leak")

    response = client.get(
        "/test-private-error", headers={"Origin": "http://testserver"}
    )
    error(response, 500, "INTERNAL_ERROR")
    assert "private-error" not in response.text
    assert response.headers["access-control-allow-origin"] == "http://testserver"


def test_cross_application_file_recovery(tmp_path):
    from twoworlds.api.app import create_app
    from twoworlds.storage.sqlite import SQLiteRepository

    path = tmp_path / "restart.sqlite"
    with TestClient(create_app(repository=SQLiteRepository(path))) as first:
        created = account(first)
    repo = SQLiteRepository(path)
    with TestClient(create_app(repository=repo)) as second:
        recovered = second.post(
            "/api/sessions/recover", json={"recovery_key": created["recovery_key"]}
        ).json()
        assert recovered["account"] == created["account"]
        assert (
            second.get("/api/me", headers=bearer(recovered["session"]["token"])).json()[
                "account"
            ]
            == created["account"]
        )
        with repo._transaction() as db:
            assert db.execute("SELECT count(*) FROM accounts").fetchone()[0] == 1


def test_cors_exact_and_app_isolation(clients):
    client, app, _ = clients()
    other, other_app, _ = clients()
    assert app.state.identity_service is not other_app.state.identity_service
    good = client.options(
        "/api/me",
        headers={
            "Origin": "http://testserver",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert good.headers["access-control-allow-origin"] == "http://testserver"
    assert good.headers["cache-control"] == "no-store"
    bad = client.options(
        "/api/me",
        headers={
            "Origin": "https://evil.invalid",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" not in bad.headers
    assert "access-control-allow-credentials" not in good.headers


@pytest.mark.parametrize(
    "code,status",
    [
        ("INVALID_INPUT", 422),
        ("CONCURRENT_UPDATE", 409),
        ("GENERATION_FAILED", 503),
        ("CLOCK_ERROR", 503),
        ("DEPENDENCY_UNAVAILABLE", 503),
        ("UNAUTHENTICATED", 401),
    ],
)
def test_identity_error_mapping(clients, code, status):
    from twoworlds.application.identity import IdentityError

    client, app, _ = clients()

    @app.get("/test-error")
    def route():
        raise IdentityError(code)

    response = client.get("/test-error")
    error(response, status, code)


def test_factory_rejects_wildcard_cors(clients):
    from twoworlds.api.app import create_app

    _, _, repo = clients()
    with pytest.raises(ValueError):
        create_app(repository=repo, allowed_origins=["*"])


def test_duplicate_authorization_malformed_json_and_unknown_routes(clients):
    client, _, _ = clients()
    created = account(client)
    response = client.get(
        "/api/me",
        headers=[
            ("Authorization", "Bearer " + created["session"]["token"]),
            ("Authorization", "Bearer ignored"),
        ],
    )
    error(response, 401, "UNAUTHENTICATED")
    response = client.post(
        "/api/sessions/recover",
        content='{"recovery_key":"secret-invalid-json"',
        headers={"content-type": "application/json"},
    )
    error(response, 422, "INVALID_INPUT")
    assert "secret-invalid-json" not in response.text
    error(client.get("/missing"), 404, "NOT_FOUND")
    error(client.post("/api/me"), 405, "METHOD_NOT_ALLOWED")


def test_current_session_expiry_not_other_devices(clients, clocks):
    clock, _ = clocks
    client, _, _ = clients(identity_clock=lambda: clock[0])
    first = account(client)
    clock[0] += timedelta(days=1)
    second = client.post(
        "/api/sessions/recover", json={"recovery_key": first["recovery_key"]}
    ).json()
    original = client.get("/api/me", headers=bearer(first["session"]["token"]))
    recovered = client.get("/api/me", headers=bearer(second["session"]["token"]))
    assert original.json()["session"] == {"expires_at": first["session"]["expires_at"]}
    assert recovered.json()["session"] == {
        "expires_at": second["session"]["expires_at"]
    }
    assert original.json()["session"] != recovered.json()["session"]


def test_real_mongo_http_identity(mongo_repository_factory):
    from twoworlds.api.app import create_app

    repo = mongo_repository_factory()
    with TestClient(create_app(repository=repo)) as client:
        created = account(client)
        recovered = client.post(
            "/api/sessions/recover", json={"recovery_key": created["recovery_key"]}
        ).json()
        assert recovered["account"] == created["account"]
        assert (
            client.get("/api/me", headers=bearer(recovered["session"]["token"])).json()[
                "account"
            ]
            == created["account"]
        )
        assert (
            client.delete(
                "/api/sessions/current", headers=bearer(created["session"]["token"])
            ).status_code
            == 204
        )
        error(
            client.get("/api/me", headers=bearer(created["session"]["token"])),
            401,
            "UNAUTHENTICATED",
        )
