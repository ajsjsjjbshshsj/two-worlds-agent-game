"""Explicit loopback-only HTTP/WebSocket launcher for local development."""

from collections.abc import Mapping
import os
import secrets
import sys
from urllib.parse import urlsplit


def create_dev_app(environ: Mapping[str, str] | None = None, *, publication_store=None):
    """No module-level app: validate settings before opening a repository."""
    env = os.environ if environ is None else environ
    backend = env.get("TWOWORLDS_STORAGE_BACKEND")
    origins = tuple(
        x.strip() for x in env.get("TWOWORLDS_ALLOWED_ORIGINS", "").split(",")
    )
    if backend not in {"sqlite", "mongo"} or not origins or any(not x for x in origins):
        raise ValueError("Select storage and exact allowed origins explicitly")
    for origin in origins:
        parsed = urlsplit(origin)
        if (
            "*" in origin
            or parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Allowed origins must be exact HTTP origins")
    if backend == "sqlite" and not env.get("TWOWORLDS_SQLITE_PATH"):
        raise ValueError("Explicit SQLite path required")
    if backend == "mongo" and not (env.get("MONGO_URI") and env.get("MONGO_DATABASE")):
        raise ValueError("Explicit Mongo URI and database required")

    from twoworlds.security.mailer import build_email_sender

    # No implicit console fallback: the email mode must be chosen explicitly.
    sender = build_email_sender(env)
    secret = env.get("TWOWORLDS_VERIFICATION_SECRET")
    if secret is None:
        # Dev-only ephemeral key: restarting invalidates outstanding codes.
        # Production must inject a durable secret through the environment.
        secret = secrets.token_urlsafe(32)
    secure = env.get("TWOWORLDS_COOKIE_SECURE", "").lower() in {"1", "true"}

    # All concrete adapters are constructed only inside this explicit factory.
    # The existing app lifespan owns closing the repository.
    from twoworlds.api.app import create_app
    from twoworlds.storage.mongo import MongoRepository
    from twoworlds.storage.sqlite import SQLiteRepository

    repository = None
    try:
        repository = (
            SQLiteRepository(env["TWOWORLDS_SQLITE_PATH"])
            if backend == "sqlite"
            else MongoRepository(env["MONGO_URI"], env["MONGO_DATABASE"])
        )
        return create_app(
            repository=repository,
            allowed_origins=origins,
            publication_store=publication_store,
            email_sender=sender,
            verification_secret=secret,
            cookie_secure=secure,
        )
    except Exception:
        if repository is not None:
            repository.close()
        # Connection exceptions can include credentials; never propagate them.
        raise ValueError(
            "Development startup failed; check storage, email and origin settings"
        ) from None


def main() -> int:
    from twoworlds.realtime.protocol import MAX_CLIENT_MESSAGE_BYTES

    try:
        port = int(os.environ.get("TWOWORLDS_DEV_PORT", "8000"))
        if not 1 <= port <= 65535:
            raise ValueError("Invalid port")
        app = create_dev_app()
        import uvicorn

        uvicorn.run(
            app,
            host="127.0.0.1",
            port=port,
            access_log=False,
            proxy_headers=False,
            log_level="critical",
            server_header=False,
            ws="websockets-sansio",
            ws_max_size=MAX_CLIENT_MESSAGE_BYTES,
            ws_ping_interval=None,
            ws_per_message_deflate=False,
        )
        return 0
    except Exception:
        print(
            "Development server startup failed. Check storage, email, origins and port settings.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
