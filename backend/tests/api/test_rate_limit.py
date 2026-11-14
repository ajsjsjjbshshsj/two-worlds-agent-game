from concurrent.futures import ThreadPoolExecutor

import pytest


def test_separate_ip_route_buckets_and_expiry(clients, clocks):
    _, clock = clocks
    client, _, _ = clients(rate_clock=lambda: clock[0])
    for _ in range(5):
        assert (
            client.post("/api/accounts", json={"display_name": "旅人"}).status_code
            == 200
        )
    blocked = client.post(
        "/api/accounts",
        json={"display_name": "旅人"},
        headers={"X-Forwarded-For": "different"},
    )
    assert blocked.status_code == 429 and blocked.headers["cache-control"] == "no-store"
    assert blocked.json()["error"] == {
        "code": "RATE_LIMITED",
        "message": "请求过于频繁，请稍后重试。",
        "retryable": True,
    }
    assert blocked.headers["retry-after"] == "60"
    for _ in range(5):
        assert (
            client.post(
                "/api/sessions/recover", json={"recovery_key": "wrong"}
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/api/sessions/recover", json={"recovery_key": "different"}
        ).status_code
        == 429
    )
    clock[0] = 59.1
    assert (
        client.post("/api/accounts", json={"display_name": "旅人"}).headers[
            "retry-after"
        ]
        == "1"
    )
    clock[0] = 60
    assert (
        client.post("/api/accounts", json={"display_name": "旅人"}).status_code == 200
    )


def test_limiter_thread_safety_memory_and_fail_closed():
    from twoworlds.api.rate_limit import RateLimiter

    clock = [0.0]
    limiter = RateLimiter(limit=5, window=60, max_keys=2, clock=lambda: clock[0])
    with ThreadPoolExecutor(12) as pool:
        values = list(pool.map(lambda _: limiter.check("create", "same-ip"), range(20)))
    assert values.count(None) == 5
    assert limiter.check("recover", "other-ip") is None
    assert limiter.check("create", "new-ip") == 60
    assert limiter.size == 2
    clock[0] = 60
    assert limiter.check("create", "new-ip") is None
    assert limiter.size == 1


def test_invalid_body_counts_before_business_and_instance_scope(clients):
    client, _, _ = clients(rate_limit=1)
    assert client.post("/api/accounts", json={"display_name": 123}).status_code == 422
    assert (
        client.post("/api/accounts", json={"display_name": "旅人"}).status_code == 429
    )
    other, _, _ = clients(rate_limit=1)
    assert other.post("/api/accounts", json={"display_name": "旅人"}).status_code == 200


@pytest.mark.parametrize(
    "path,body,first_status",
    [
        ("/api/accounts", {"display_name": "旅人"}, 200),
        ("/api/sessions/recover", {"recovery_key": "wrong"}, 401),
    ],
)
@pytest.mark.parametrize("origin", ["http://testserver", "https://evil.invalid", None])
def test_rate_limit_retry_after_cors(clients, path, body, first_status, origin):
    client, _, _ = clients(rate_limit=1)
    headers = {"Origin": origin} if origin else {}
    assert client.post(path, json=body, headers=headers).status_code == first_status
    response = client.post(path, json=body, headers=headers)
    assert response.status_code == 429
    assert response.headers["retry-after"] == "60"
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["error"]["code"] == "RATE_LIMITED"
    if origin == "http://testserver":
        assert response.headers["access-control-allow-origin"] == origin
        assert response.headers["access-control-expose-headers"] == "Retry-After"
        assert response.headers["vary"] == "Origin"
    else:
        assert "access-control-allow-origin" not in response.headers
        assert "access-control-expose-headers" not in response.headers
    assert "access-control-allow-credentials" not in response.headers


def test_inner_cors_middleware_exposes_retry_after(clients):
    client, _, _ = clients()
    response = client.get("/api/me", headers={"Origin": "http://testserver"})
    assert response.status_code == 401
    assert response.headers["access-control-allow-origin"] == "http://testserver"
    assert response.headers["access-control-expose-headers"] == "Retry-After"
    assert "access-control-allow-credentials" not in response.headers
