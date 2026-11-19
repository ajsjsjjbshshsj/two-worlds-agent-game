"""HTTP rate limiting backed by shared database counters (no per-process budget)."""

from datetime import timedelta

from fastapi.testclient import TestClient

from tests.identity_support import (
    ORIGIN,
    ORIGIN_HEADER,
    PASSWORD,
    RELAXED_POLICIES,
    register,
    request_code,
    unique_email,
)


def policies(**overrides):
    return RELAXED_POLICIES | overrides


def peer_client(app, ip):
    # The limiter trusts only the socket peer, so tests change the ASGI client
    # address instead of sending forgeable X-Forwarded-For headers. Lifespan is
    # answered locally: the owning TestClient must keep the shared app open.
    async def peer_scope(scope, receive, send):
        if scope["type"] == "lifespan":
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return
            return
        if scope["type"] == "http":
            scope = dict(scope, client=(ip, 40000))
        await app(scope, receive, send)

    return TestClient(peer_scope)


def code_body(email, purpose="register"):
    return {"email": email, "purpose": purpose}


def assert_limited(response, retry_after):
    assert response.status_code == 429, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["retry-after"] == str(retry_after)
    assert response.json()["error"] == {
        "code": "RATE_LIMITED",
        "message": "请求过于频繁，请稍后重试。",
        "retryable": True,
    }


def test_code_requests_per_email_minute_and_window(clients, clocks):
    from twoworlds.application.rate_limit import RateLimitPolicy

    clock, _ = clocks
    client, _, _ = clients(
        identity_clock=lambda: clock[0],
        rate_policies=policies(code_email_minute=RateLimitPolicy(1, 60)),
    )
    email = unique_email()
    request_code(client, email)
    blocked = client.post(
        "/api/verification-codes", json=code_body(email), headers=ORIGIN_HEADER
    )
    assert_limited(blocked, 60)
    # A different email has its own budget.
    request_code(client, unique_email("other"))
    clock[0] += timedelta(seconds=59)
    blocked = client.post(
        "/api/verification-codes", json=code_body(email), headers=ORIGIN_HEADER
    )
    assert_limited(blocked, 1)
    clock[0] += timedelta(seconds=1)
    request_code(client, email)


def test_code_requests_per_email_hour(clients, clocks):
    from twoworlds.application.rate_limit import RateLimitPolicy

    clock, _ = clocks
    client, _, _ = clients(
        identity_clock=lambda: clock[0],
        rate_policies=policies(
            code_email_minute=RateLimitPolicy(100, 60),
            code_email_hour=RateLimitPolicy(2, 3600),
        ),
    )
    email = unique_email()
    request_code(client, email)
    clock[0] += timedelta(seconds=61)
    request_code(client, email)
    clock[0] += timedelta(seconds=61)
    blocked = client.post(
        "/api/verification-codes", json=code_body(email), headers=ORIGIN_HEADER
    )
    assert_limited(blocked, 3600 - 122)


def test_code_requests_per_ip_hour(clients):
    from twoworlds.application.rate_limit import RateLimitPolicy

    client, app, _ = clients(
        rate_policies=policies(code_ip_hour=RateLimitPolicy(2, 3600))
    )
    request_code(client, unique_email("one"))
    request_code(client, unique_email("two"))
    blocked = client.post(
        "/api/verification-codes",
        json=code_body(unique_email("three")),
        headers=ORIGIN_HEADER,
    )
    assert_limited(blocked, 3600)
    with peer_client(app, "203.0.113.7") as other:
        request_code(other, unique_email("three"))
    # Forwarded headers are never trusted as a budget escape hatch.
    blocked = client.post(
        "/api/verification-codes",
        json=code_body(unique_email("four")),
        headers=ORIGIN_HEADER | {"X-Forwarded-For": "203.0.113.99"},
    )
    assert_limited(blocked, 3600)


def test_login_per_ip_email_combo(clients):
    from twoworlds.application.rate_limit import RateLimitPolicy

    client, app, _ = clients(
        rate_policies=policies(login_minute=RateLimitPolicy(2, 60))
    )
    who = register(client)
    email = who["account"]["email"]
    body = {"email": email, "password": PASSWORD + "!"}
    for _ in range(2):
        assert (
            client.post("/api/sessions", json=body, headers=ORIGIN_HEADER).status_code
            == 401
        )
    blocked = client.post("/api/sessions", json=body, headers=ORIGIN_HEADER)
    assert_limited(blocked, 60)
    # Another email from the same IP keeps its own budget.
    assert (
        client.post(
            "/api/sessions",
            json={"email": unique_email("other"), "password": PASSWORD},
            headers=ORIGIN_HEADER,
        ).status_code
        == 401
    )
    # The same email from another IP is a different combo key.
    with peer_client(app, "203.0.113.7") as other:
        assert (
            other.post("/api/sessions", json=body, headers=ORIGIN_HEADER).status_code
            == 401
        )
    # Even the correct password cannot bypass the exhausted budget.
    blocked = client.post(
        "/api/sessions",
        json={"email": email, "password": PASSWORD},
        headers=ORIGIN_HEADER,
    )
    assert_limited(blocked, 60)


def test_two_app_instances_share_one_budget(clients, tmp_path):
    from twoworlds.application.rate_limit import RateLimitPolicy

    path = tmp_path / "shared.sqlite"
    tight = policies(login_minute=RateLimitPolicy(2, 60))
    first, _, _ = clients(path=path, rate_policies=tight)
    second, _, _ = clients(path=path, rate_policies=tight)
    who = register(first)
    body = {"email": who["account"]["email"], "password": PASSWORD}
    assert (
        first.post("/api/sessions", json=body, headers=ORIGIN_HEADER).status_code == 200
    )
    assert (
        second.post("/api/sessions", json=body, headers=ORIGIN_HEADER).status_code
        == 200
    )
    assert_limited(first.post("/api/sessions", json=body, headers=ORIGIN_HEADER), 60)
    assert_limited(second.post("/api/sessions", json=body, headers=ORIGIN_HEADER), 60)


def test_counters_survive_app_restart(clients, tmp_path):
    from twoworlds.application.rate_limit import RateLimitPolicy

    path = tmp_path / "restart.sqlite"
    tight = policies(code_email_minute=RateLimitPolicy(1, 60))
    email = unique_email()
    first, _, _ = clients(path=path, rate_policies=tight)
    request_code(first, email)
    first.close()
    second, _, _ = clients(path=path, rate_policies=tight)
    assert_limited(
        second.post(
            "/api/verification-codes", json=code_body(email), headers=ORIGIN_HEADER
        ),
        60,
    )


def test_schema_validation_precedes_budget_consumption(clients):
    from twoworlds.application.rate_limit import RateLimitPolicy

    client, _, _ = clients(rate_policies=policies(login_minute=RateLimitPolicy(1, 60)))
    # A body without a usable email cannot be keyed, so it is refused by the
    # schema without spending the combo budget.
    assert (
        client.post(
            "/api/sessions", json={"email": 123}, headers=ORIGIN_HEADER
        ).status_code
        == 422
    )
    body = {"email": unique_email(), "password": PASSWORD}
    assert (
        client.post("/api/sessions", json=body, headers=ORIGIN_HEADER).status_code
        == 401
    )
    assert_limited(client.post("/api/sessions", json=body, headers=ORIGIN_HEADER), 60)


def test_rate_limit_retry_after_cors(clients):
    from twoworlds.application.rate_limit import RateLimitPolicy

    client, _, _ = clients(
        rate_policies=policies(code_email_minute=RateLimitPolicy(1, 60))
    )
    email = unique_email()
    assert (
        client.post(
            "/api/verification-codes", json=code_body(email), headers=ORIGIN_HEADER
        ).status_code
        == 202
    )
    response = client.post(
        "/api/verification-codes", json=code_body(email), headers=ORIGIN_HEADER
    )
    assert response.status_code == 429
    assert response.headers["retry-after"] == "60"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert response.headers["access-control-expose-headers"] == "Retry-After"
    assert response.headers["vary"] == "Origin"


def test_foreign_origin_is_csrf_before_any_budget(clients):
    from twoworlds.application.rate_limit import RateLimitPolicy

    client, _, _ = clients(
        rate_policies=policies(code_email_minute=RateLimitPolicy(1, 60))
    )
    email = unique_email()
    for _ in range(3):
        response = client.post(
            "/api/verification-codes",
            json=code_body(email),
            headers={"Origin": "https://evil.invalid"},
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "CSRF_REJECTED"
        assert "access-control-allow-origin" not in response.headers
    # The refused requests never touched the counter for this email.
    request_code(client, email)


def test_missing_origin_is_csrf_before_rate_limit(clients):
    client, _, _ = clients()
    response = client.post("/api/verification-codes", json=code_body(unique_email()))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "CSRF_REJECTED"


def test_inner_cors_middleware_exposes_retry_after(clients):
    client, _, _ = clients()
    response = client.get("/api/me", headers={"Origin": ORIGIN})
    assert response.status_code == 401
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert response.headers["access-control-expose-headers"] == "Retry-After"
    assert response.headers["access-control-allow-credentials"] == "true"
