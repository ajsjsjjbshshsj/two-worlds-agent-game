"""Container and production application launcher with explicit environment validation.

Supports two strictly separated execution modes:
1. 'production' (or 'formal'):
   - Requires TWOWORLDS_STORAGE_BACKEND=mongo
   - Requires MONGO_URI and MONGO_DATABASE
   - Requires TWOWORLDS_VERIFICATION_SECRET (explicit durable secret; no ephemeral dev fallback)
   - Requires TWOWORLDS_ALLOWED_ORIGINS (exact HTTP/HTTPS origins; no wildcard)
   - Requires TWOWORLDS_EMAIL_MODE=smtp and valid SMTP settings
   - Validates AI mode ('demo' or 'provider' with valid ProviderConfig)
   - Connects to MongoRepository (with ping check). If unreachable, fails immediately without fallback.
2. 'demo':
   - Requires TWOWORLDS_STORAGE_BACKEND=sqlite
   - Requires TWOWORLDS_SQLITE_PATH
   - Requires TWOWORLDS_ALLOWED_ORIGINS
   - Allows TWOWORLDS_EMAIL_MODE=console for local verification codes
   - Enforces TWOWORLDS_AI_MODE=demo (forbids external AI provider)
   - Connects to SQLiteRepository.

Neither mode falls back to the other or to in-memory storage.
"""

from collections.abc import Mapping
import os
import sys
from urllib.parse import urlsplit

VALID_MODES = {"production", "formal", "demo"}


def validate_origins(raw_origins: str) -> tuple[str, ...]:
    origins = tuple(x.strip() for x in raw_origins.split(",") if x.strip())
    if not origins:
        raise ValueError("Explicit allowed origins required")
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
            raise ValueError(f"Origin must be an exact HTTP/HTTPS origin: {origin!r}")
    return origins


def create_server_app(
    environ: Mapping[str, str] | None = None, *, publication_store=None
):
    env = os.environ if environ is None else environ
    mode = env.get("TWOWORLDS_MODE")
    if mode not in VALID_MODES:
        raise ValueError("Explicit TWOWORLDS_MODE required: 'production' or 'demo'")

    production = mode in {"production", "formal"}
    if production and env.get("TWOWORLDS_EMAIL_MODE") != "smtp":
        raise ValueError("Production mode requires TWOWORLDS_EMAIL_MODE=smtp")

    backend = env.get("TWOWORLDS_STORAGE_BACKEND")
    raw_origins = env.get("TWOWORLDS_ALLOWED_ORIGINS", "")
    origins = validate_origins(raw_origins)

    from twoworlds.ai.providers.config import load_provider_config
    from twoworlds.api.app import create_app
    from twoworlds.security.mailer import build_email_sender
    from twoworlds.storage.mongo import MongoRepository
    from twoworlds.storage.sqlite import SQLiteRepository

    sender = build_email_sender(env)
    secure = env.get("TWOWORLDS_COOKIE_SECURE", "").lower() in {"1", "true"}

    if production:
        if backend != "mongo":
            raise ValueError("Production mode requires TWOWORLDS_STORAGE_BACKEND=mongo")
        mongo_uri = env.get("MONGO_URI")
        mongo_database = env.get("MONGO_DATABASE")
        if not mongo_uri or not mongo_database:
            raise ValueError("Production mode requires MONGO_URI and MONGO_DATABASE")
        secret = env.get("TWOWORLDS_VERIFICATION_SECRET")
        if not secret or len(secret.strip()) < 16:
            raise ValueError(
                "Production mode requires explicit durable TWOWORLDS_VERIFICATION_SECRET (min 16 chars)"
            )

        ai_mode = env.get("TWOWORLDS_AI_MODE", "demo")
        narrative_config = None
        if ai_mode == "provider":
            narrative_config = load_provider_config(env)
            if narrative_config is None:
                raise ValueError(
                    "TWOWORLDS_AI_MODE=provider requires valid provider settings"
                )
        elif ai_mode != "demo":
            raise ValueError("Invalid TWOWORLDS_AI_MODE; select 'demo' or 'provider'")

        repository = None
        try:
            repository = MongoRepository(mongo_uri, mongo_database)
        except Exception:
            raise ConnectionError(
                "Production MongoDB connection failed; server will not start without database"
            ) from None

        return create_app(
            repository=repository,
            ai_mode=ai_mode,
            narrative_config=narrative_config,
            allowed_origins=origins,
            publication_store=publication_store,
            email_sender=sender,
            verification_secret=secret,
            cookie_secure=secure,
        )

    else:  # mode == "demo"
        if backend != "sqlite":
            raise ValueError("Demo mode requires TWOWORLDS_STORAGE_BACKEND=sqlite")
        sqlite_path = env.get("TWOWORLDS_SQLITE_PATH")
        if not sqlite_path:
            raise ValueError("Demo mode requires TWOWORLDS_SQLITE_PATH")

        ai_mode = env.get("TWOWORLDS_AI_MODE", "demo")
        if ai_mode != "demo":
            raise ValueError(
                "Demo mode forbids external AI provider; use TWOWORLDS_AI_MODE=demo"
            )

        secret = env.get("TWOWORLDS_VERIFICATION_SECRET")
        if not secret:
            import secrets

            secret = secrets.token_urlsafe(32)

        repository = SQLiteRepository(sqlite_path)
        return create_app(
            repository=repository,
            ai_mode="demo",
            allowed_origins=origins,
            publication_store=publication_store,
            email_sender=sender,
            verification_secret=secret,
            cookie_secure=secure,
        )


def main() -> int:
    from twoworlds.realtime.protocol import MAX_CLIENT_MESSAGE_BYTES

    try:
        host = os.environ.get("TWOWORLDS_HOST", "0.0.0.0")
        port_raw = os.environ.get("TWOWORLDS_PORT", "8000")
        try:
            port = int(port_raw)
        except ValueError:
            raise ValueError(f"Invalid port: {port_raw}") from None
        if not 1 <= port <= 65535:
            raise ValueError("Port must be between 1 and 65535")

        app = create_server_app()
        import uvicorn

        uvicorn.run(
            app,
            host=host,
            port=port,
            access_log=False,
            proxy_headers=True,
            server_header=False,
            log_level="info",
            ws="websockets-sansio",
            ws_max_size=MAX_CLIENT_MESSAGE_BYTES,
            ws_ping_interval=None,
            ws_per_message_deflate=False,
        )
        return 0
    except Exception as exc:
        sys.stderr.write(f"Server startup failed: {exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
