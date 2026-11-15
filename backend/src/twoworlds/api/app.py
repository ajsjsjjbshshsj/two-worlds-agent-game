"""Explicit application assembly; importing this module opens no database."""

from contextlib import asynccontextmanager, ExitStack
from importlib import resources
import time
from urllib.parse import urlsplit

from fastapi import FastAPI
from starlette.datastructures import MutableHeaders
from starlette.middleware.cors import CORSMiddleware

from twoworlds.application.identity import IdentityService
from twoworlds.application.pairs import PairService
from twoworlds.application.saves import SaveService
from twoworlds.content.publication import PublicationStore
from twoworlds.ports.repository import Repository

from .errors import failure, install_handlers
from .rate_limit import RateLimiter
from .routers import accounts, pairs, saves, sessions

MAX_BODY_BYTES = 16 * 1024


def _declared_body_too_large(headers):
    limit = str(MAX_BODY_BYTES)
    for value in headers.getlist("content-length"):
        for field in value.split(","):
            length = field.strip().lstrip("0")
            # Compare decimal strings without converting an untrusted huge integer.
            if (
                length.isascii()
                and length.isdecimal()
                and (
                    len(length) > len(limit)
                    or (len(length) == len(limit) and length > limit)
                )
            ):
                return True
    return False


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
                if "Retry-After" in response.headers:
                    response.headers["Access-Control-Expose-Headers"] = "Retry-After"
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
            headers = MutableHeaders(raw=list(scope.get("headers", [])))
            if _declared_body_too_large(headers):
                return await reject(
                    failure(413, "REQUEST_TOO_LARGE", "请求正文超过允许的大小。")
                )

            # Bound buffering before FastAPI parses JSON, including chunked bodies.
            # Oversized frames are rejected before copying; do not drain the tail.
            buffer = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                chunk = message.get("body", b"")
                if len(buffer) + len(chunk) > MAX_BODY_BYTES:
                    return await reject(
                        failure(413, "REQUEST_TOO_LARGE", "请求正文超过允许的大小。")
                    )
                buffer.extend(chunk)
                if not message.get("more_body", False):
                    break

            body = bytes(buffer)
            del buffer
            replayed = False

            async def replay():
                nonlocal replayed
                if not replayed:
                    replayed = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return await receive()

            await self.app(scope, replay, no_store)
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
    pair_clock=None,
    publication_store: PublicationStore | None = None,
    save_clock=None,
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
            with ExitStack() as stack:
                store = publication_store
                if store is None:
                    # Keep extracted wheel/zip resources alive for the app lifetime.
                    root = stack.enter_context(
                        resources.as_file(
                            resources.files("twoworlds.content").joinpath("published")
                        )
                    )
                    store = PublicationStore(root)
                clock = save_clock if save_clock is not None else identity_clock
                app.state.save_service = SaveService(
                    repository,
                    store,
                    **({"clock": clock} if clock is not None else {}),
                )
                yield
        finally:
            repository.close()

    app = FastAPI(lifespan=lifespan, redirect_slashes=False)
    app.state.identity_service = IdentityService(
        repository, **({"clock": identity_clock} if identity_clock is not None else {})
    )
    clock = pair_clock if pair_clock is not None else identity_clock
    app.state.pair_service = PairService(
        repository, **({"clock": clock} if clock is not None else {})
    )
    limiter = RateLimiter(
        limit=rate_limit, window=rate_window, max_keys=rate_max_keys, clock=rate_clock
    )
    install_handlers(app)
    app.include_router(accounts.router)
    app.include_router(sessions.router)
    app.include_router(pairs.router)
    app.include_router(saves.router)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
        expose_headers=["Retry-After"],
    )
    app.add_middleware(IdentitySafety, limiter=limiter, origins=origins)
    return app
