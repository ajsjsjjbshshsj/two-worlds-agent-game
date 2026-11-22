"""Explicit application assembly; importing this module opens no database."""

from contextlib import asynccontextmanager, ExitStack
from importlib import resources
from urllib.parse import urlsplit

from fastapi import FastAPI
from starlette.datastructures import MutableHeaders
from starlette.middleware.cors import CORSMiddleware

from twoworlds.ai.graph import NarrativeLimits
from twoworlds.application.identity import IdentityService
from twoworlds.application.pairs import PairService
from twoworlds.application.rate_limit import RateLimitPolicy, SharedRateLimiter
from twoworlds.application.saves import SaveService
from twoworlds.application.verification import VerificationCodeService
from twoworlds.content.publication import PublicationStore
from twoworlds.ports.email import EmailCodeSender
from twoworlds.ports.repository import Repository
from twoworlds.realtime.protocol import WebSocketTiming

from .errors import failure, install_handlers
from .routers import (
    accounts,
    pairs,
    password_resets,
    saves,
    sessions,
    verification,
    websocket,
)

MAX_BODY_BYTES = 16 * 1024
_STATE_CHANGING = {"POST", "PUT", "PATCH", "DELETE"}

DEFAULT_RATE_POLICIES = {
    "code_email_minute": RateLimitPolicy(1, 60),
    "code_email_hour": RateLimitPolicy(5, 3600),
    "code_ip_hour": RateLimitPolicy(10, 3600),
    "login_minute": RateLimitPolicy(5, 60),
    "login_hour": RateLimitPolicy(20, 3600),
    # Per-IP ceiling so rotating the email cannot bypass Argon2 work unbounded.
    "login_ip_minute": RateLimitPolicy(30, 60),
    "login_ip_hour": RateLimitPolicy(300, 3600),
}


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
    def __init__(self, app, *, origins):
        self.app, self.origins = app, origins

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
            headers = MutableHeaders(raw=list(scope.get("headers", [])))
            if scope["method"] in _STATE_CHANGING and scope["path"].startswith("/api/"):
                # SameSite=Lax alone is not enough: require one exact Origin.
                values = headers.getlist("origin")
                if len(values) != 1 or values[0] not in self.origins:
                    return await reject(
                        failure(403, "CSRF_REJECTED", "请求来源未被允许。")
                    )
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
    email_sender: EmailCodeSender,
    verification_secret: str,
    cookie_secure: bool = False,
    rate_policies=None,
    rate_max_keys=10000,
    websocket_timing: WebSocketTiming | None = None,
    narrative_limits: NarrativeLimits = NarrativeLimits(),
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
    if type(cookie_secure) is not bool:
        raise ValueError("cookie_secure must be a boolean")
    if ai_mode != "demo":
        # The local graph is always available. Real providers require a later integration.
        raise ValueError("only demo AI mode is implemented")
    policies = dict(DEFAULT_RATE_POLICIES)
    if rate_policies is not None:
        for name, policy in rate_policies.items():
            if name not in policies or not isinstance(policy, RateLimitPolicy):
                raise ValueError("Unknown or invalid rate policy")
            policies[name] = policy

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
                    narrative_limits=narrative_limits,
                    **({"clock": clock} if clock is not None else {}),
                )
                yield
        finally:
            # Drain background sends first: their failure invalidation still
            # needs the repository.
            app.state.verification_service.close()
            repository.close()

    app = FastAPI(lifespan=lifespan, redirect_slashes=False)
    app.state.allowed_origins = frozenset(origins)
    app.state.websocket_timing = websocket_timing or WebSocketTiming()
    app.state.email_sender = email_sender
    app.state.identity_service = IdentityService(
        repository, **({"clock": identity_clock} if identity_clock is not None else {})
    )
    app.state.verification_service = VerificationCodeService(
        repository,
        email_sender,
        secret=verification_secret,
        **({"clock": identity_clock} if identity_clock is not None else {}),
    )
    app.state.rate_limiter = SharedRateLimiter(
        repository,
        max_keys=rate_max_keys,
        **({"clock": identity_clock} if identity_clock is not None else {}),
    )
    app.state.rate_policies = policies
    app.state.cookie_secure = cookie_secure
    clock = pair_clock if pair_clock is not None else identity_clock
    app.state.pair_service = PairService(
        repository, **({"clock": clock} if clock is not None else {})
    )
    install_handlers(app)
    app.include_router(accounts.router)
    app.include_router(sessions.router)
    app.include_router(verification.router)
    app.include_router(password_resets.router)
    app.include_router(pairs.router)
    app.include_router(saves.router)
    app.include_router(websocket.router)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type"],
        expose_headers=["Retry-After"],
    )
    app.add_middleware(IdentitySafety, origins=origins)
    return app
