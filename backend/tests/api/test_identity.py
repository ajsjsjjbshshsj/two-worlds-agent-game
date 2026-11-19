from datetime import timedelta
import logging
from threading import Event
import time

from fastapi.testclient import TestClient
import pytest

from tests.identity_support import (
    ORIGIN,
    ORIGIN_HEADER,
    PASSWORD,
    RELAXED_POLICIES,
    TEST_SECRET,
    FakeEmailSender,
    auth,
    login,
    register,
    request_code,
    unique_email,
)


def open_app(repo, **options):
    from twoworlds.api.app import create_app

    options.setdefault("email_sender", FakeEmailSender())
    options.setdefault("verification_secret", TEST_SECRET)
    options.setdefault("rate_policies", RELAXED_POLICIES)
    return create_app(
        repository=repo, ai_mode="demo", allowed_origins=[ORIGIN], **options
    )


def error(response, status, code):
    assert response.status_code == status, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "retryable"}
    assert body["error"]["code"] == code
    assert type(body["error"]["retryable"]) is bool


def assert_session_cookie(response, *, secure=False):
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("tw_session=")
    for attribute in ("HttpOnly", "SameSite=lax", "Path=/", "Max-Age=604800"):
        assert attribute in cookie
    assert "Domain" not in cookie
    assert ("Secure" in cookie) is secure


def assert_cleared_cookie(response):
    cookie = response.headers["set-cookie"]
    assert cookie.startswith('tw_session="";')
    assert "Max-Age=0" in cookie and "expires=" in cookie.lower()
    for attribute in ("HttpOnly", "SameSite=lax", "Path=/"):
        assert attribute in cookie


def test_register_shape_cookie_and_digest_storage(clients, caplog):
    from twoworlds.security.passwords import verify_password

    caplog.set_level(logging.INFO)
    client, _, repo = clients()
    email = unique_email()
    request_code(client, email)
    code = client.app.state.email_sender.code_for(email, "register")
    response = client.post(
        "/api/accounts",
        json={
            "email": email,
            "code": code,
            "password": PASSWORD,
            "display_name": "旅人",
        },
        headers=ORIGIN_HEADER,
    )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert set(body) == {"account", "session"}
    assert set(body["account"]) == {"id", "email", "display_name"}
    assert body["account"]["email"] == email
    assert set(body["session"]) == {"expires_at"}
    assert "token" not in response.text
    assert_session_cookie(response)
    token = response.cookies.get("tw_session")
    me = client.get("/api/me", headers=auth({"token": token}))
    assert me.status_code == 200 and me.json() == body
    assert me.headers["cache-control"] == "no-store"
    stored = repo.get_account(body["account"]["id"])
    assert verify_password(stored.password_hash, PASSWORD)
    for secret in (token, PASSWORD, code):
        assert secret not in caplog.text
        assert secret not in stored.model_dump_json()
    assert stored.sessions[0].token_digest not in me.text + response.text + caplog.text


def test_login_cookie_and_unified_credentials_error(clients):
    client, _, _ = clients()
    who = register(client)
    response = client.post(
        "/api/sessions",
        json={"email": who["account"]["email"], "password": PASSWORD},
        headers=ORIGIN_HEADER,
    )
    assert response.status_code == 200, response.text
    assert_session_cookie(response)
    again = response.cookies.get("tw_session")
    assert again != who["token"]
    assert response.json()["account"] == who["account"]
    assert client.get("/api/me", headers=auth({"token": again})).status_code == 200
    assert client.get("/api/me", headers=auth(who)).status_code == 200
    wrong = client.post(
        "/api/sessions",
        json={"email": who["account"]["email"], "password": PASSWORD + "!"},
        headers=ORIGIN_HEADER,
    )
    unknown = client.post(
        "/api/sessions",
        json={"email": unique_email(), "password": PASSWORD},
        headers=ORIGIN_HEADER,
    )
    error(wrong, 401, "INVALID_CREDENTIALS")
    error(unknown, 401, "INVALID_CREDENTIALS")
    # Wrong password and unknown email are indistinguishable to the caller.
    assert wrong.json() == unknown.json()


def test_bearer_is_ignored_and_cookie_rejections(clients):
    client, _, _ = clients()
    who = register(client)
    # An explicit non-session Cookie overrides the TestClient jar, so these
    # requests really arrive without a session (a valid Bearer must not help).
    for headers in (
        {"Cookie": "other=none"},
        {"Cookie": "other=none", "Authorization": "Bearer " + who["token"]},
        {"Cookie": "other=none", "Authorization": "Basic secret"},
        {"Cookie": "other=none", "Authorization": "Bearer"},
        {"Cookie": "tw_session=bad"},
        {"Cookie": "tw_session="},
        {"Cookie": f"tw_session={who['account']['id']}"},
        {"Cookie": "other=value"},
    ):
        error(client.get("/api/me", headers=headers), 401, "UNAUTHENTICATED")
    error(
        client.get(
            "/api/me",
            params={"token": who["token"]},
            headers={"Cookie": "other=none"},
        ),
        401,
        "UNAUTHENTICATED",
    )
    duplicate = client.get(
        "/api/me",
        headers=[
            ("Cookie", f"tw_session={who['token']}"),
            ("Cookie", "tw_session=ignored"),
        ],
    )
    error(duplicate, 401, "UNAUTHENTICATED")


def test_logout_clears_cookie_and_only_current_session(clients):
    client, _, repo = clients()
    who = register(client)
    other = login(client, who)
    response = client.delete("/api/sessions/current", headers=auth(who))
    assert response.status_code == 204 and response.content == b""
    assert response.headers["cache-control"] == "no-store"
    assert_cleared_cookie(response)
    error(client.get("/api/me", headers=auth(who)), 401, "UNAUTHENTICATED")
    error(
        client.delete("/api/sessions/current", headers=auth(who)),
        401,
        "UNAUTHENTICATED",
    )
    assert client.get("/api/me", headers=auth(other)).status_code == 200
    assert repo.get_account(who["account"]["id"]) is not None


def test_expiry_eviction_and_clock_error_http(clients, clocks):
    clock, _ = clocks
    client, _, _ = clients(identity_clock=lambda: clock[0])
    who = register(client)
    tokens = [who["token"]]
    start = clock[0]
    for _ in range(5):
        clock[0] += timedelta(seconds=1)
        tokens.append(login(client, who)["token"])
    error(
        client.get("/api/me", headers=auth({"token": tokens[0]})),
        401,
        "UNAUTHENTICATED",
    )
    clock[0] = start + timedelta(seconds=4)
    error(client.get("/api/me", headers=auth({"token": tokens[1]})), 503, "CLOCK_ERROR")
    clock[0] = start + timedelta(seconds=5, days=7)
    error(
        client.get("/api/me", headers=auth({"token": tokens[-1]})),
        401,
        "UNAUTHENTICATED",
    )


@pytest.mark.parametrize(
    "body",
    [
        {},
        {
            "email": "not-an-email",
            "code": "123456",
            "password": PASSWORD,
            "display_name": "旅人",
        },
        {
            "email": "a@b.co",
            "code": "12345",
            "password": PASSWORD,
            "display_name": "旅人",
        },
        {
            "email": "a@b.co",
            "code": "abcdef",
            "password": PASSWORD,
            "display_name": "旅人",
        },
        {
            "email": "a@b.co",
            "code": "123456",
            "password": "short",
            "display_name": "旅人",
        },
        {
            "email": "a@b.co",
            "code": "123456",
            "password": "x" * 129,
            "display_name": "旅人",
        },
        {
            "email": "a@b.co",
            "code": "123456",
            "password": PASSWORD,
            "display_name": " ",
        },
        {
            "email": "a@b.co",
            "code": "123456",
            "password": PASSWORD,
            "display_name": "x" * 41,
        },
    ],
)
def test_register_schema_invalid(clients, body):
    client, _, _ = clients()
    error(
        client.post("/api/accounts", json=body, headers=ORIGIN_HEADER),
        422,
        "INVALID_INPUT",
    )


@pytest.mark.parametrize(
    "field", ["account_id", "player_id", "role", "user_id", "recovery_key"]
)
def test_extra_fields_do_not_echo_inputs(clients, field):
    client, _, _ = clients()
    marker = "private-input-do-not-echo"
    response = client.post(
        "/api/accounts",
        json={
            "email": unique_email(),
            "code": "123456",
            "password": PASSWORD,
            "display_name": "旅人",
            field: marker,
        },
        headers=ORIGIN_HEADER,
    )
    error(response, 422, "INVALID_INPUT")
    assert marker not in response.text


def test_register_code_errors_and_duplicate_after_valid_code(clients):
    client, _, _ = clients()
    email = unique_email()
    # No code requested at all.
    error(
        client.post(
            "/api/accounts",
            json={
                "email": email,
                "code": "123456",
                "password": PASSWORD,
                "display_name": "旅人",
            },
            headers=ORIGIN_HEADER,
        ),
        422,
        "INVALID_CODE",
    )
    request_code(client, email)
    code = client.app.state.email_sender.code_for(email, "register")
    wrong = ("1" if code[0] != "1" else "2") + code[1:]
    error(
        client.post(
            "/api/accounts",
            json={
                "email": email,
                "code": wrong,
                "password": PASSWORD,
                "display_name": "旅人",
            },
            headers=ORIGIN_HEADER,
        ),
        422,
        "INVALID_CODE",
    )
    who = register(client, email)
    # Enumeration parity: a registered email still gets a register code, and
    # the 409 only appears after that valid code is consumed.
    request_code(client, email)
    fresh = client.app.state.email_sender.code_for(email, "register")
    response = client.post(
        "/api/accounts",
        json={
            "email": email,
            "code": fresh,
            "password": PASSWORD,
            "display_name": "别人",
        },
        headers=ORIGIN_HEADER,
    )
    error(response, 409, "EMAIL_ALREADY_REGISTERED")
    assert (
        client.get("/api/me", headers=auth(who)).json()["account"]["display_name"]
        == "玩家"
    )


def test_reset_flow_revokes_all_sessions_and_clears_cookie(clients):
    client, _, _ = clients()
    who = register(client)
    other = login(client, who)
    email = who["account"]["email"]
    request_code(client, email, "reset")
    code = client.app.state.email_sender.code_for(email, "reset")
    response = client.post(
        "/api/password-resets",
        json={"email": email, "code": code, "new_password": "new password 77"},
        headers=ORIGIN_HEADER | {"Cookie": f"tw_session={who['token']}"},
    )
    assert response.status_code == 204 and response.content == b""
    assert response.headers["cache-control"] == "no-store"
    assert_cleared_cookie(response)
    error(client.get("/api/me", headers=auth(who)), 401, "UNAUTHENTICATED")
    error(client.get("/api/me", headers=auth(other)), 401, "UNAUTHENTICATED")
    error(
        client.post(
            "/api/sessions",
            json={"email": email, "password": PASSWORD},
            headers=ORIGIN_HEADER,
        ),
        401,
        "INVALID_CREDENTIALS",
    )
    fresh = client.post(
        "/api/sessions",
        json={"email": email, "password": "new password 77"},
        headers=ORIGIN_HEADER,
    )
    assert fresh.status_code == 200
    # The consumed reset code cannot be replayed.
    error(
        client.post(
            "/api/password-resets",
            json={"email": email, "code": code, "new_password": "another one 88"},
            headers=ORIGIN_HEADER,
        ),
        422,
        "INVALID_CODE",
    )


def test_reset_code_enumeration_parity(clients):
    client, _, _ = clients()
    who = register(client)
    unknown_email = unique_email()
    unknown = request_code(client, unknown_email, "reset")
    known = request_code(client, who["account"]["email"], "reset")
    assert unknown.status_code == known.status_code == 202
    assert unknown.json() == known.json() == {"status": "accepted"}
    sender = client.app.state.email_sender
    assert all(email != unknown_email for email, _, _ in sender.sent)
    assert sender.code_for(who["account"]["email"], "reset")


def test_code_request_stays_202_on_send_failure(clients):
    client, app, repo = clients()
    app.state.email_sender.fail = True
    email = unique_email()
    response = client.post(
        "/api/verification-codes",
        json={"email": email, "purpose": "register"},
        headers=ORIGIN_HEADER,
    )
    assert response.status_code == 202
    assert response.json() == {"status": "accepted"}
    assert app.state.verification_service.wait_for_delivery(10)
    from twoworlds.application.verification import code_id

    assert repo.get_verification_code(code_id(email, "register")).consumed_at


def test_slow_delivery_never_delays_the_202_response(clients):
    gate = Event()
    client, app, _ = clients(email_sender=FakeEmailSender(gate=gate))
    started = time.monotonic()
    response = client.post(
        "/api/verification-codes",
        json={"email": unique_email(), "purpose": "register"},
        headers=ORIGIN_HEADER,
    )
    elapsed = time.monotonic() - started
    assert response.status_code == 202
    assert response.json() == {"status": "accepted"}
    # The fake transport is still blocked, proving the response did not wait.
    assert app.state.email_sender.sent == []
    assert elapsed < 5
    gate.set()
    assert app.state.verification_service.wait_for_delivery(10)
    assert len(app.state.email_sender.sent) == 1


def test_dependency_failure_and_unknown_exception_safe(clients):
    client, app, repo = clients()
    who = register(client)
    repo.close()
    error(client.get("/api/me", headers=auth(who)), 503, "DEPENDENCY_UNAVAILABLE")

    @app.get("/test-private-error")
    def broken():
        raise RuntimeError("private-error-must-not-leak")

    response = client.get("/test-private-error", headers=ORIGIN_HEADER)
    error(response, 500, "INTERNAL_ERROR")
    assert "private-error" not in response.text
    assert response.headers["access-control-allow-origin"] == ORIGIN


def test_cross_application_file_login(tmp_path):
    from twoworlds.storage.sqlite import SQLiteRepository

    path = tmp_path / "restart.sqlite"
    with TestClient(open_app(SQLiteRepository(path))) as first:
        who = register(first)
    repo = SQLiteRepository(path)
    with TestClient(open_app(repo)) as second:
        again = login(second, who)
        assert again["account"] == who["account"]
        me = second.get("/api/me", headers=auth(again))
        assert me.json()["account"] == who["account"]
        with repo._transaction() as db:
            assert db.execute("SELECT count(*) FROM accounts").fetchone()[0] == 1


def test_cors_preflight_credentials_and_app_isolation(clients):
    client, app, _ = clients()
    other, other_app, _ = clients()
    assert app.state.identity_service is not other_app.state.identity_service
    good = client.options(
        "/api/me",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert good.headers["access-control-allow-origin"] == ORIGIN
    assert good.headers["access-control-allow-credentials"] == "true"
    assert good.headers["cache-control"] == "no-store"
    bad = client.options(
        "/api/me",
        headers={
            "Origin": "https://evil.invalid",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert "access-control-allow-origin" not in bad.headers


@pytest.mark.parametrize(
    "code,status",
    [
        ("INVALID_INPUT", 422),
        ("INVALID_CREDENTIALS", 401),
        ("EMAIL_ALREADY_REGISTERED", 409),
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

    error(client.get("/test-error"), status, code)


@pytest.mark.parametrize(
    "code,status",
    [
        ("INVALID_INPUT", 422),
        ("INVALID_CODE", 422),
        ("CODE_EXPIRED", 422),
        ("CODE_LOCKED", 422),
        ("CONCURRENT_UPDATE", 409),
        ("DEPENDENCY_UNAVAILABLE", 503),
    ],
)
def test_verification_error_mapping(clients, code, status):
    from twoworlds.application.verification import VerificationError

    client, app, _ = clients()

    @app.get("/test-error")
    def route():
        raise VerificationError(code)

    error(client.get("/test-error"), status, code)


def test_rate_limit_error_mapping_sets_retry_after(clients):
    from twoworlds.application.rate_limit import RateLimitError

    client, app, _ = clients()

    @app.get("/test-error")
    def route():
        raise RateLimitError("RATE_LIMITED", 42)

    response = client.get("/test-error")
    error(response, 429, "RATE_LIMITED")
    assert response.headers["retry-after"] == "42"
    assert response.json()["error"]["retryable"] is True


def test_factory_rejects_bad_configuration(clients):
    from twoworlds.application.rate_limit import RateLimitPolicy
    from twoworlds.api.app import create_app

    _, _, repo = clients()
    with pytest.raises(ValueError):
        create_app(
            repository=repo,
            allowed_origins=["*"],
            email_sender=FakeEmailSender(),
            verification_secret=TEST_SECRET,
        )
    with pytest.raises(TypeError):
        create_app(
            repository=repo, allowed_origins=[ORIGIN], email_sender=FakeEmailSender()
        )
    with pytest.raises(ValueError):
        create_app(
            repository=repo,
            allowed_origins=[ORIGIN],
            email_sender=FakeEmailSender(),
            verification_secret=TEST_SECRET,
            cookie_secure="yes",
        )
    with pytest.raises(ValueError):
        create_app(
            repository=repo,
            allowed_origins=[ORIGIN],
            email_sender=FakeEmailSender(),
            verification_secret=TEST_SECRET,
            rate_policies={"unknown": RateLimitPolicy(1, 60)},
        )


def test_malformed_json_and_unknown_routes(clients):
    client, _, _ = clients()
    response = client.post(
        "/api/sessions",
        content='{"password":"secret-invalid-json"',
        headers=ORIGIN_HEADER | {"content-type": "application/json"},
    )
    error(response, 422, "INVALID_INPUT")
    assert "secret-invalid-json" not in response.text
    error(client.get("/missing"), 404, "NOT_FOUND")
    error(client.post("/api/me", headers=ORIGIN_HEADER), 405, "METHOD_NOT_ALLOWED")


def test_method_not_allowed_preserves_allow_header(clients):
    client, _, _ = clients()
    response = client.post("/api/me", headers=ORIGIN_HEADER)
    error(response, 405, "METHOD_NOT_ALLOWED")
    assert "GET" in {method.strip() for method in response.headers["allow"].split(",")}
    assert response.json() == {
        "error": {
            "code": "METHOD_NOT_ALLOWED",
            "message": "请求无法处理。",
            "retryable": False,
        }
    }


def test_http_exception_preserves_headers_without_overriding_no_store(clients):
    from starlette.exceptions import HTTPException

    client, app, _ = clients()

    @app.get("/test-http-headers")
    def route():
        raise HTTPException(
            404,
            detail="private-error-detail",
            headers={
                "X-Error-Policy": "retained",
                "Cache-Control": "public, max-age=60",
            },
        )

    response = client.get("/test-http-headers")
    error(response, 404, "NOT_FOUND")
    assert response.headers["x-error-policy"] == "retained"
    assert response.json() == {
        "error": {
            "code": "NOT_FOUND",
            "message": "请求无法处理。",
            "retryable": False,
        }
    }


def test_current_session_expiry_not_other_devices(clients, clocks):
    clock, _ = clocks
    client, _, _ = clients(identity_clock=lambda: clock[0])
    first = register(client)
    clock[0] += timedelta(days=1)
    second = login(client, first)
    original = client.get("/api/me", headers=auth(first))
    refreshed = client.get("/api/me", headers=auth(second))
    assert original.json()["session"] == {"expires_at": first["session"]["expires_at"]}
    assert refreshed.json()["session"] == {
        "expires_at": second["session"]["expires_at"]
    }
    assert original.json()["session"] != refreshed.json()["session"]


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Origin": "null"},
        {"Origin": "https://evil.invalid"},
        {"Origin": ORIGIN + "/"},
        {"Origin": ORIGIN.upper()},
        [("Origin", ORIGIN), ("Origin", ORIGIN)],
    ],
)
def test_state_changing_requests_require_exact_origin(clients, headers):
    client, _, _ = clients()
    response = client.post(
        "/api/verification-codes",
        json={"email": unique_email(), "purpose": "register"},
        headers=headers,
    )
    error(response, 403, "CSRF_REJECTED")


def test_csrf_precedes_auth_and_get_is_exempt(clients):
    client, _, _ = clients()
    who = register(client)
    cookie = {"Cookie": f"tw_session={who['token']}"}
    # GET carries no state change, so it needs no Origin.
    assert client.get("/api/me", headers=cookie).status_code == 200
    # CSRF is checked before credentials: even a valid cookie cannot bypass it.
    error(client.delete("/api/sessions/current", headers=cookie), 403, "CSRF_REJECTED")
    error(
        client.post(
            "/api/sessions",
            json={"email": who["account"]["email"], "password": PASSWORD},
        ),
        403,
        "CSRF_REJECTED",
    )
    assert client.get("/api/me", headers=auth(who)).status_code == 200


def test_secure_cookie_flag_in_production_mode(clients):
    client, _, _ = clients(cookie_secure=True)
    email = unique_email()
    request_code(client, email)
    response = client.post(
        "/api/accounts",
        json={
            "email": email,
            "code": client.app.state.email_sender.code_for(email, "register"),
            "password": PASSWORD,
            "display_name": "旅人",
        },
        headers=ORIGIN_HEADER,
    )
    assert response.status_code == 200
    assert_session_cookie(response, secure=True)
    token = response.cookies.get("tw_session")
    logout = client.delete("/api/sessions/current", headers=auth({"token": token}))
    assert logout.status_code == 204
    assert "Secure" in logout.headers["set-cookie"]


def test_real_mongo_http_identity(mongo_repository_factory):
    repo = mongo_repository_factory()
    with TestClient(open_app(repo)) as client:
        who = register(client)
        again = login(client, who)
        assert again["account"] == who["account"]
        me = client.get("/api/me", headers=auth(again))
        assert me.json()["account"] == who["account"]
        assert (
            client.delete("/api/sessions/current", headers=auth(who)).status_code == 204
        )
        error(client.get("/api/me", headers=auth(who)), 401, "UNAUTHENTICATED")
        assert client.get("/api/me", headers=auth(again)).status_code == 200
