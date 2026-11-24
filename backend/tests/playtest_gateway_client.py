"""TCP client executed from distinct isolated ingress network addresses."""

from contextlib import ExitStack, suppress
import json
import socket
import ssl
import sys
import warnings

import httpx
from websockets.exceptions import InvalidStatus
from websockets.sync.client import connect

ORIGIN = "https://gateway"
HTTPS = ORIGIN + ":8443"
TLS = ssl.create_default_context(cafile="/trust.pem")


def socket_status(path, *, origin=ORIGIN, headers=None):
    try:
        with connect(
            "wss://gateway:8443" + path,
            ssl=TLS,
            open_timeout=6,
            proxy=None,
            origin=origin,
            additional_headers=headers,
        ) as ws:
            return json.loads(ws.recv(timeout=6))
    except InvalidStatus as error:
        return error.response.status_code


def login(client, credentials):
    reply = client.post(
        "/api/sessions",
        json={key: credentials[key] for key in ("email", "password")},
    )
    reply.raise_for_status()
    cookie = reply.headers["set-cookie"].lower()
    assert all(flag in cookie for flag in ("secure", "httponly", "samesite=lax"))
    return client.cookies["tw_session"]


def authorized(client, options):
    assert client.get("/").status_code == 200
    assert client.get("/sw.js").status_code == 200
    assert client.get("/api/me").status_code == 401
    assert client.get("/health/ready").status_code == 404
    assert client.get("/api/docs").status_code == 404
    for closed in ("/api/accounts", "/api/verification-codes", "/api/password-resets"):
        assert client.post(closed, json={}).status_code == 404
    assert (
        client.post(
            "/api/sessions", headers={"Origin": "http://gateway"}, json={}
        ).status_code
        == 403
    )

    cookie = login(client, options["accounts"][0])
    with httpx.Client(
        base_url=HTTPS, verify=TLS, trust_env=False, headers={"Origin": ORIGIN}
    ) as partner:
        login(partner, options["accounts"][1])
        pair = client.post("/api/pairs").raise_for_status().json()
        partner.post(
            "/api/pairs/join", json={"invite_token": pair["invite_token"]}
        ).raise_for_status()
        save = (
            client.post(
                "/api/saves",
                json={
                    "pair_id": pair["id"],
                    "script_id": "lighthouse",
                    "script_version": "1.0.0",
                },
            )
            .raise_for_status()
            .json()
        )
        save_path = "/api/saves/" + save["id"]
        path = save_path + "/media/old_tower"
        media = client.get(path)
        assert media.status_code == 200 and media.content.startswith(b"\x89PNG")
        assert media.headers["cache-control"] == "no-store"
        assert partner.get(path).status_code == 404
        assert client.get(path, headers={"Cookie": "other=none"}).status_code == 401

    ws = "/api/ws/saves/" + save["id"]
    assert socket_status(ws) == 403
    headers = {"Cookie": "tw_session=" + cookie}
    assert socket_status(ws, headers=headers, origin="http://gateway") == 403
    snapshot = socket_status(ws, headers=headers)
    assert (
        snapshot["type"] == "snapshot"
        and snapshot["save"] == client.get(save_path).json()
    )
    assert client.get("/api/me").status_code == 200
    return {
        "media": path,
        "ws": ws,
        "cookie": headers["Cookie"],
        "invite": pair["invite_token"],
    }


def tls_and_network(client, options):
    for version in (ssl.TLSVersion.TLSv1_2, ssl.TLSVersion.TLSv1_3):
        tls = ssl.create_default_context(cafile="/trust.pem")
        tls.minimum_version = tls.maximum_version = version
        with (
            socket.create_connection(("gateway", 8443), timeout=3) as raw,
            tls.wrap_socket(raw, server_hostname="gateway") as connection,
        ):
            assert (
                connection.version()
                == {
                    ssl.TLSVersion.TLSv1_2: "TLSv1.2",
                    ssl.TLSVersion.TLSv1_3: "TLSv1.3",
                }[version]
            )
    tls = ssl.create_default_context(cafile="/trust.pem")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        tls.minimum_version = tls.maximum_version = ssl.TLSVersion.TLSv1_1
    tls.set_ciphers("DEFAULT:@SECLEVEL=0")
    with socket.create_connection(("gateway", 8443), timeout=3) as raw:
        try:
            with tls.wrap_socket(raw, server_hostname="gateway"):
                raise AssertionError("TLS 1.1 negotiated")
        except ssl.SSLError:
            pass
    for host, port in [("gateway", 80), *options["internal_endpoints"]]:
        with suppress(OSError), socket.create_connection((host, port), timeout=2):
            raise AssertionError("Private or plaintext port reachable from ingress")
    try:
        reply = client.get("http://gateway:8443/api/me")
    except httpx.TransportError:
        pass
    else:
        assert reply.status_code == 400 and not reply.is_redirect


def main():
    action = sys.argv[1]
    options = json.load(sys.stdin)
    with ExitStack() as stack:
        client = stack.enter_context(
            httpx.Client(
                base_url=HTTPS,
                verify=TLS,
                trust_env=False,
                headers={"Origin": ORIGIN},
                timeout=6,
            )
        )
        if action == "allowed":
            tls_and_network(client, options)
            print(json.dumps(authorized(client, options)))
        elif action == "denied":
            headers = {
                "Cookie": options["cookie"],
                "X-Forwarded-For": options["allowed"],
                "X-Real-IP": options["allowed"],
                "Forwarded": "for=" + options["allowed"],
            }
            for path in ("/", "/sw.js", "/api/me", options["media"]):
                assert client.get(path, headers=headers).status_code == 403
            assert socket_status(options["ws"], headers=headers) == 403
        elif action == "revoked":
            headers = {"Cookie": options["cookie"]}
            assert client.get("/api/me", headers=headers).status_code == 401
            assert socket_status(options["ws"], headers=headers) == 403
        elif action == "closed":
            with (
                suppress(OSError),
                socket.create_connection(("gateway", 8443), timeout=3),
            ):
                raise AssertionError("Stopped Playtest ingress is still reachable")
        else:
            raise AssertionError("Unknown ingress check")


if __name__ == "__main__":
    main()
