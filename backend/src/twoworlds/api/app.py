"""Explicit application assembly; importing this module opens no database."""

from contextlib import asynccontextmanager
import time
from urllib.parse import urlsplit

from fastapi import FastAPI
from starlette.datastructures import MutableHeaders
from starlette.middleware.cors import CORSMiddleware

from twoworlds.application.identity import IdentityService
from twoworlds.ports.repository import Repository

from .errors import failure, install_handlers
from .rate_limit import RateLimiter
from .routers import accounts, sessions


class IdentitySafety:
    def __init__(self, app, *, limiter, origins):
        self.app, self.limiter, self.origins = app, limiter, origins

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started = False

        async def no_store(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                MutableHeaders(scope=message)["Cache-Control"] = "no-store"
            await send(message)

        async def reject(response):
            # These responses originate outside CORS; retain the exact allowlist.
            headers = MutableHeaders(raw=list(scope.get("headers", [])))
            origin = headers.get("origin")
            if origin in self.origins:
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers["Vary"] = "Origin"
            await response(scope, receive, no_store)

        try:
            if scope["method"] == "POST" and scope["path"] in {
                "/api/accounts",
                "/api/sessions/recover",
            }:
                # Read only the peer address, never forwarded IPs or request bodies.
                peer = scope.get("client")
                retry = self.limiter.check(
                    scope["path"], peer[0] if peer else "unknown"
                )
                if retry is not None:
                    return await reject(
                        failure(
                            429,
                            "RATE_LIMITED",
                            "请求过于频繁，请稍后重试。",
                            True,
                            {"Retry-After": str(retry)},
                        )
                    )
            await self.app(scope, receive, no_store)
        except Exception:
            if started:
                raise
            # Never log the exception or request: either may contain credentials.
            await reject(failure(500, "INTERNAL_ERROR", "服务暂时无法处理请求。", True))


def create_app(
    *,
    repository: Repository,
    ai_mode="demo",
    allowed_origins=(),
    identity_clock=None,
    rate_clock=time.monotonic,
    rate_limit=5,
    rate_window=60,
    rate_max_keys=10000,
):
    origins = list(allowed_origins)
    for origin in origins:
        parsed = urlsplit(origin)
        if (
            "*" in origin
            or parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("CORS origins must be exact HTTP origins")

    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            repository.close()

    app = FastAPI(lifespan=lifespan, redirect_slashes=False)
    app.state.identity_service = IdentityService(
        repository, **({"clock": identity_clock} if identity_clock is not None else {})
    )
    limiter = RateLimiter(
        limit=rate_limit, window=rate_window, max_keys=rate_max_keys, clock=rate_clock
    )
    install_handlers(app)
    app.include_router(accounts.router)
    app.include_router(sessions.router)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.add_middleware(IdentitySafety, limiter=limiter, origins=origins)
    return app
