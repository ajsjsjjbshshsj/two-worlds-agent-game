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
from copy import copy, deepcopy
from ipaddress import ip_address
import logging
import os
import sys
from urllib.parse import urlsplit

VALID_MODES = {"production", "formal", "demo"}


class ServerConfigurationError(ValueError):
    """A fixed, safe startup message."""


class ServerDatabaseUnavailable(ConnectionError):
    """A startup storage failure without connection details."""


class ServerLogFilter(logging.Filter):
    def filter(self, record):
        # Uvicorn includes the untrusted query string in WebSocket handshake logs.
        if isinstance(record.msg, str) and record.msg.startswith('%s - "WebSocket %s"'):
            status = (
                record.args[2]
                if len(record.args) == 3
                else (403 if record.msg.endswith(" 403") else 101)
            )
            record = copy(record)
            record.msg, record.args = "WebSocket handshake status=%d", (status,)
        # ASGI lifespan failures arrive as preformatted traceback strings.
        if (
            record.exc_info
            or record.exc_text
            or (
                isinstance(record.msg, str)
                and record.msg.startswith("Traceback (most recent call last):")
            )
        ):
            record = copy(record)
            record.msg, record.args = "Server request or lifecycle error", ()
            record.exc_info = record.exc_text = record.stack_info = None
        return record


def validate_origins(raw_origins: str) -> tuple[str, ...]:
    origins = tuple(x.strip() for x in raw_origins.split(",") if x.strip())
    if not origins:
        raise ServerConfigurationError("Explicit allowed origins required")
    for origin in origins:
        try:
            parsed = urlsplit(origin)
            port = parsed.port
            if (
                "*" in origin
                or parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or origin != f"{parsed.scheme}://{parsed.netloc}"
                or parsed.netloc.endswith(":")
                or port == 0
                or any(ch.isspace() or ord(ch) < 33 for ch in origin)
            ):
                raise ValueError
        except ValueError:
            raise ServerConfigurationError(
                "Origin must be an exact HTTP/HTTPS origin"
            ) from None
    return origins


def trusted_proxy_ip(raw: str) -> str:
    if not raw:
        return ""
    try:
        address = ip_address(raw)
        if address.is_unspecified or "%" in raw:
            raise ValueError
        return str(address)
    except ValueError:
        raise ServerConfigurationError(
            "TWOWORLDS_TRUSTED_PROXY_IP must be a single explicit IP address"
        ) from None


def create_server_app(
    environ: Mapping[str, str] | None = None, *, publication_store=None
):
    env = os.environ if environ is None else environ
    mode = env.get("TWOWORLDS_MODE")
    if mode not in VALID_MODES:
        raise ServerConfigurationError(
            "Explicit TWOWORLDS_MODE required: 'production' or 'demo'"
        )

    production = mode in {"production", "formal"}
    if production and env.get("TWOWORLDS_EMAIL_MODE") != "smtp":
        raise ServerConfigurationError(
            "Production mode requires TWOWORLDS_EMAIL_MODE=smtp"
        )

    backend = env.get("TWOWORLDS_STORAGE_BACKEND")
    raw_origins = env.get("TWOWORLDS_ALLOWED_ORIGINS", "")
    origins = validate_origins(raw_origins)

    from twoworlds.ai.providers.config import load_provider_config
    from twoworlds.api.app import create_app
    from twoworlds.security.mailer import build_email_sender
    from twoworlds.storage.mongo import MongoRepository
    from twoworlds.storage.sqlite import SQLiteRepository

    secure = env.get("TWOWORLDS_COOKIE_SECURE", "").lower() in {"1", "true"}
    if production and (
        not secure or any(not source.startswith("https://") for source in origins)
    ):
        raise ServerConfigurationError(
            "Production mode requires secure cookies and exact HTTPS origins"
        )
    sender = build_email_sender(env)

    if production:
        if backend != "mongo":
            raise ServerConfigurationError(
                "Production mode requires TWOWORLDS_STORAGE_BACKEND=mongo"
            )
        mongo_uri = env.get("MONGO_URI")
        mongo_database = env.get("MONGO_DATABASE")
        if not mongo_uri or not mongo_database:
            raise ServerConfigurationError(
                "Production mode requires MONGO_URI and MONGO_DATABASE"
            )
        secret = env.get("TWOWORLDS_VERIFICATION_SECRET")
        if not secret or len(secret.strip()) < 16:
            raise ServerConfigurationError(
                "Production mode requires explicit durable TWOWORLDS_VERIFICATION_SECRET (min 16 chars)"
            )

        ai_mode = env.get("TWOWORLDS_AI_MODE", "demo")
        narrative_config = None
        if ai_mode == "provider":
            narrative_config = load_provider_config(env)
            if narrative_config is None:
                raise ServerConfigurationError(
                    "TWOWORLDS_AI_MODE=provider requires valid provider settings"
                )
        elif ai_mode != "demo":
            raise ServerConfigurationError(
                "Invalid TWOWORLDS_AI_MODE; select 'demo' or 'provider'"
            )

        repository = None
        try:
            repository = MongoRepository(mongo_uri, mongo_database)
        except Exception:
            raise ServerDatabaseUnavailable(
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
            raise ServerConfigurationError(
                "Demo mode requires TWOWORLDS_STORAGE_BACKEND=sqlite"
            )
        sqlite_path = env.get("TWOWORLDS_SQLITE_PATH")
        if not sqlite_path:
            raise ServerConfigurationError("Demo mode requires TWOWORLDS_SQLITE_PATH")

        ai_mode = env.get("TWOWORLDS_AI_MODE", "demo")
        if ai_mode != "demo":
            raise ServerConfigurationError(
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
    from twoworlds.ai.providers.config import ProviderConfigError
    from twoworlds.realtime.protocol import MAX_CLIENT_MESSAGE_BYTES
    from twoworlds.security.mailer import EmailConfigurationError

    try:
        host = os.environ.get("TWOWORLDS_HOST", "0.0.0.0")
        port_raw = os.environ.get("TWOWORLDS_PORT", "8000")
        try:
            port = int(port_raw)
        except ValueError:
            raise ServerConfigurationError(
                "TWOWORLDS_PORT must be an integer"
            ) from None
        if not 1 <= port <= 65535:
            raise ServerConfigurationError("Port must be between 1 and 65535")

        proxy_ip = trusted_proxy_ip(os.environ.get("TWOWORLDS_TRUSTED_PROXY_IP", ""))
        app = create_server_app()
        import uvicorn

        log_config = deepcopy(uvicorn.config.LOGGING_CONFIG)
        log_config["filters"] = {"safe_server": {"()": ServerLogFilter}}
        log_config["handlers"]["default"]["filters"] = ["safe_server"]

        uvicorn.run(
            app,
            host=host,
            port=port,
            access_log=False,
            proxy_headers=bool(proxy_ip),
            forwarded_allow_ips=proxy_ip,
            log_config=log_config,
            server_header=False,
            log_level="info",
            ws="websockets-sansio",
            ws_max_size=MAX_CLIENT_MESSAGE_BYTES,
            ws_ping_interval=None,
            ws_per_message_deflate=False,
        )
        return 0
    except (
        ServerConfigurationError,
        ServerDatabaseUnavailable,
        EmailConfigurationError,
        ProviderConfigError,
    ) as exc:
        sys.stderr.write(f"Server startup failed: {exc}\n")
    except Exception:
        sys.stderr.write("Server startup failed: unexpected application error\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
