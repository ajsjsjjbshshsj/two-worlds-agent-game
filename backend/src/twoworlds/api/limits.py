"""Rate-limit key derivation and enforcement for HTTP routers.

Only the socket peer address is used; forwarded headers are never trusted.
Emails and IPs are digested before reaching the shared counter store.
"""

from hashlib import sha256

from fastapi import Request


def digest_key(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def client_ip(request: Request) -> str:
    peer = request.scope.get("client")
    return peer[0] if peer else "unknown"


def check_limits(request: Request, *checks: tuple[str, str]) -> None:
    state = request.app.state
    for policy_name, key in checks:
        state.rate_limiter.hit(key, state.rate_policies[policy_name])
