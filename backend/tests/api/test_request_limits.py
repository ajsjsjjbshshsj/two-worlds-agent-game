import asyncio
import json
import logging

import httpx
import pytest

LIMIT = 16384
ORIGIN = b"http://testserver"


def padded_body(size):
    value = json.dumps(
        {"email": "traveler@example.com", "password": "correct horse 9"}
    ).encode()
    assert len(value) <= size
    return value + b" " * (size - len(value))


def raw_request(
    app, chunks, *, headers=(), method="POST", path="/api/sessions", default_origin=True
):
    """Send distinct ASGI frames; TestClient coalesces iterable request bodies."""
    sent = []
    reads = 0

    async def run():
        async def receive():
            nonlocal reads
            if reads == len(chunks):
                return {"type": "http.disconnect"}
            body = chunks[reads]
            reads += 1
            return {
                "type": "http.request",
                "body": body,
                "more_body": reads < len(chunks),
            }

        async def send(message):
            sent.append(message)

        await app(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "scheme": "http",
                "method": method,
                "path": path,
                "raw_path": path.encode(),
                "query_string": b"",
                "root_path": "",
                "headers": [
                    (b"content-type", b"application/json"),
                    *([(b"origin", ORIGIN)] if default_origin else []),
                    *headers,
                ],
                "client": ("127.0.0.1", 1234),
                "server": ("testserver", 80),
            },
            receive,
            send,
        )

    asyncio.run(run())
    start = next(
        message for message in sent if message["type"] == "http.response.start"
    )
    response = httpx.Response(
        start["status"],
        headers=start["headers"],
        content=b"".join(
            message.get("body", b"")
            for message in sent
            if message["type"] == "http.response.body"
        ),
    )
    return response, reads


def assert_too_large(response):
    assert response.status_code == 413
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "error": {
            "code": "REQUEST_TOO_LARGE",
            "message": "请求正文超过允许的大小。",
            "retryable": False,
        }
    }


def assert_parsed_login(response):
    # A parsed body reaches the login rule and is refused as unknown credentials;
    # an unparsed body would have produced 422 INVALID_INPUT instead.
    assert response.status_code == 401, response.text
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("size", [64, LIMIT])
def test_normal_and_exact_limit_body_still_parse(clients, size):
    client, _, _ = clients()
    body = padded_body(size)
    assert len(body) == size
    response = client.post(
        "/api/sessions",
        content=body,
        headers={"Content-Type": "application/json", "Origin": "http://testserver"},
    )
    assert_parsed_login(response)


def test_over_limit_testclient_request_is_rejected(clients):
    client, _, _ = clients()
    response = client.post(
        "/api/sessions",
        content=padded_body(LIMIT + 1),
        headers={"Content-Type": "application/json", "Origin": "http://testserver"},
    )
    assert_too_large(response)


@pytest.mark.parametrize("declared", [b"16385", b"999999999999999999999999"])
def test_excess_content_length_rejects_before_reading(clients, declared):
    _, app, _ = clients()
    response, reads = raw_request(
        app, [padded_body(64)], headers=[(b"content-length", declared)]
    )
    assert_too_large(response)
    assert reads == 0


@pytest.mark.parametrize("method,path", [("POST", "/api/sessions"), ("GET", "/api/me")])
def test_missing_content_length_uses_actual_bytes(clients, method, path):
    _, app, _ = clients()
    response, reads = raw_request(
        app, [padded_body(LIMIT + 1)], method=method, path=path
    )
    assert_too_large(response)
    assert reads == 1


@pytest.mark.parametrize("declared", [b"0", b"1", b"16384"])
def test_small_content_length_cannot_bypass_actual_limit(clients, declared):
    _, app, _ = clients()
    response, _ = raw_request(
        app, [padded_body(LIMIT + 1)], headers=[(b"content-length", declared)]
    )
    assert_too_large(response)


def test_chunked_limit_stops_reading_and_never_creates_account(clients):
    _, app, repo = clients()
    response, reads = raw_request(
        app,
        [padded_body(LIMIT), b" ", b"unread-private-tail"],
        headers=[(b"transfer-encoding", b"chunked")],
    )
    assert_too_large(response)
    assert reads == 2
    with repo._transaction() as db:
        assert db.execute("SELECT count(*) FROM accounts").fetchone()[0] == 0


def test_exact_limit_chunked_without_length_replays_to_fastapi(clients):
    _, app, _ = clients()
    body = padded_body(LIMIT)
    response, reads = raw_request(
        app,
        [body[:8000], b"", body[8000:]],
        headers=[(b"transfer-encoding", b"chunked")],
    )
    assert_parsed_login(response)
    assert reads == 3


def test_limit_counts_utf8_bytes_not_characters(clients):
    _, app, _ = clients()
    text = json.dumps(
        {"email": "traveler@example.com", "password": "界" * 6000},
        ensure_ascii=False,
    )
    body = text.encode()
    assert len(text) < LIMIT < len(body)
    response, _ = raw_request(app, [body])
    assert_too_large(response)


def test_rejection_does_not_echo_or_log_secrets(clients, caplog):
    caplog.set_level(logging.INFO)
    _, app, _ = clients()
    secret = "private-password-token-never-echo"
    body = json.dumps({"email": "a@b.co", "password": secret}).encode()
    body += b" " * (LIMIT + 1 - len(body))
    response, _ = raw_request(
        app,
        [body],
        path="/api/sessions",
        headers=[(b"authorization", ("Bearer " + secret).encode())],
    )
    assert_too_large(response)
    assert secret not in response.text + caplog.text


@pytest.mark.parametrize(
    "origin,allowed", [(b"http://testserver", True), (b"https://evil.invalid", False)]
)
def test_rejections_keep_exact_cors_allowlist(clients, origin, allowed):
    _, app, _ = clients()
    # Replace the default Origin instead of duplicating it: duplicate Origin
    # headers are themselves a CSRF rejection.
    response, _ = raw_request(
        app,
        [padded_body(LIMIT + 1)],
        headers=[(b"origin", origin)],
        default_origin=False,
    )
    if allowed:
        assert_too_large(response)
    else:
        # A foreign Origin is refused by CSRF before the body is even read.
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "CSRF_REJECTED"
        assert response.headers["cache-control"] == "no-store"
    assert (
        response.headers.get("access-control-allow-origin") == origin.decode()
    ) is allowed
    assert "access-control-allow-credentials" not in response.headers
