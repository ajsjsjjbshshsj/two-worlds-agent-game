"""Explicit application factory and launcher for isolated closed playtests."""

from collections.abc import Mapping
from copy import deepcopy
import hashlib
import os
from pathlib import Path
import re
import sys
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pymongo.errors import PyMongoError
from pymongo.uri_parser import parse_uri

from twoworlds.api.app import create_app
from twoworlds.content._publication_files import (
    MAX_RECORD_BYTES,
    parse_document,
    read_bytes,
)
from twoworlds.content.publication import PublicationStore, ReleaseRecord
from twoworlds.realtime.protocol import MAX_CLIENT_MESSAGE_BYTES
from twoworlds.security.mailer import DisabledEmailCodeSender
from twoworlds.server import ServerLogFilter, trusted_proxy_ip, validate_origins
from twoworlds.storage.mongo import MongoRepository

_AUTH_OPTIONS = {"authsource", "authmechanism"}
_MONGO_OPTIONS = _AUTH_OPTIONS | {
    "directconnection",
    "tls",
    "ssl",
    "tlscafile",
    "serverselectiontimeoutms",
}


class PlaytestConfigurationError(ValueError):
    """An operator-facing error with no configuration values."""


def _secret_file(path):
    try:
        with Path(path).open(encoding="ascii") as source:
            value = source.read(66).removesuffix("\n")
        if not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError
        return value
    except (OSError, ValueError):
        raise PlaytestConfigurationError("Invalid Playtest secret file") from None


def _mongo_target(env):
    name = env.get("TWOWORLDS_PLAYTEST_MONGO_DATABASE", "")
    uri = env.get("TWOWORLDS_PLAYTEST_MONGO_URI", "")
    password_file = env.get("TWOWORLDS_PLAYTEST_MONGO_PASSWORD_FILE", "")
    if not name or (not uri and not password_file):
        raise PlaytestConfigurationError(
            "Explicit TWOWORLDS_PLAYTEST_MONGO_URI and TWOWORLDS_PLAYTEST_MONGO_DATABASE are required"
        )
    if not re.fullmatch(r"twoworlds_playtest_[a-z0-9_]{1,40}", name):
        raise PlaytestConfigurationError(
            "Playtest requires a dedicated twoworlds_playtest_* database"
        )
    if password_file:
        if uri:
            raise PlaytestConfigurationError(
                "Choose one Playtest MongoDB credential source"
            )
        password = _secret_file(password_file)
        uri = (
            f"mongodb://playtest_app:{password}@playtest-mongo:27017/{name}"
            "?directConnection=true&authMechanism=SCRAM-SHA-256&serverSelectionTimeoutMS=4000"
        )

    try:
        parts = urlsplit(uri)
        if parts.scheme != "mongodb" or "#" in uri or ";" in parts.query:
            raise ValueError
        query = parse_qsl(parts.query, strict_parsing=True, keep_blank_values=True)
        keys = [key.lower() for key, _ in query]
        if len(keys) != len(set(keys)) or not set(keys) <= _MONGO_OPTIONS:
            raise ValueError
        parsed = parse_uri(uri)
        options = {key.lower(): value for key, value in parsed["options"].items()}
        if (
            len(parsed["nodelist"]) != 1
            or not parsed["username"]
            or not parsed["password"]
            or parsed["database"] not in (None, name)
            or parsed["collection"] is not None
            or options.get("authsource", parsed["database"]) != name
            or options.get("authmechanism", "DEFAULT")
            not in ("DEFAULT", "SCRAM-SHA-256")
            or not options.get("directconnection", True)
        ):
            raise ValueError
    except (OSError, PyMongoError, ValueError):
        raise PlaytestConfigurationError(
            "Playtest requires a single MongoDB endpoint and database-scoped SCRAM credentials"
        ) from None

    # Retain the exact endpoint and transport options for the unauthenticated probe.
    anonymous = urlunsplit(
        (
            parts.scheme,
            parts.netloc.rsplit("@", 1)[-1],
            "/",
            urlencode(
                [
                    (key, value)
                    for key, value in query
                    if key.lower() not in _AUTH_OPTIONS
                ]
            ),
            "",
        )
    )
    return uri, name, anonymous


def _verification_secret(env):
    value = env.get("TWOWORLDS_PLAYTEST_VERIFICATION_SECRET", "")
    secret_file = env.get("TWOWORLDS_PLAYTEST_VERIFICATION_SECRET_FILE", "")
    if secret_file:
        if value:
            raise PlaytestConfigurationError(
                "Choose one Playtest verification secret source"
            )
        value = _secret_file(secret_file)
    if re.fullmatch(r"[0-9a-f]{64}", value):
        raw = bytes.fromhex(value)
        # Operators generate 32 random bytes. Filter out obvious placeholders
        # including repeats and ordered sequences that only satisfy the format.
        if len(set(raw)) >= 24 and not (
            raw == bytes(sorted(raw)) or raw == bytes(sorted(raw, reverse=True))
        ):
            return value
    raise PlaytestConfigurationError(
        "TWOWORLDS_PLAYTEST_VERIFICATION_SECRET must be 32 random bytes in lowercase hex"
    )


def _playtest_settings(env):
    if env.get("TWOWORLDS_MODE") != "playtest":
        raise PlaytestConfigurationError("Explicit TWOWORLDS_MODE=playtest is required")
    if env.get("TWOWORLDS_DEMO_PUBLICATION_ROOT"):
        raise PlaytestConfigurationError(
            "Local demo publication roots are forbidden in Playtest mode"
        )
    if env.get("TWOWORLDS_AI_MODE", "demo") != "demo":
        raise PlaytestConfigurationError("Playtest requires TWOWORLDS_AI_MODE=demo")
    if env.get("TWOWORLDS_EMAIL_MODE", "disabled") != "disabled":
        raise PlaytestConfigurationError(
            "Playtest requires TWOWORLDS_EMAIL_MODE=disabled"
        )
    if env.get("TWOWORLDS_STORAGE_BACKEND", "mongo") != "mongo":
        raise PlaytestConfigurationError("Playtest requires MongoDB")

    secret = _verification_secret(env)
    return secret, _mongo_target(env)


def _connect_mongo(target):
    uri, name, anonymous = target
    try:
        return MongoRepository(uri, name, anonymous_probe_uri=anonymous)
    except Exception:
        raise PlaytestConfigurationError(
            "Playtest MongoDB unavailable or not an isolated authenticated database"
        ) from None


def open_playtest_repository(
    environ: Mapping[str, str] | None = None,
) -> MongoRepository:
    """Open the same authenticated, scoped repository for trusted offline tools."""
    env = os.environ if environ is None else environ
    _, target = _playtest_settings(env)
    return _connect_mongo(target)


def _validate_deployment_approval(env, root, catalog):
    approval = env.get("TWOWORLDS_PLAYTEST_APPROVAL_FILE", "")
    purpose = env.get("TWOWORLDS_PLAYTEST_CONTENT_PURPOSE", "")
    if not approval or not purpose:
        raise PlaytestConfigurationError(
            "Explicit TWOWORLDS_PLAYTEST_APPROVAL_FILE and TWOWORLDS_PLAYTEST_CONTENT_PURPOSE are required"
        )
    try:
        if not catalog or purpose not in {"internal-drill", "participant"}:
            raise ValueError
        path = Path(approval).absolute()
        signed = parse_document(read_bytes(path.parent.resolve(), path.name, 65536))
        sealed = {}
        for script in catalog:
            version = f"{script.id}/{script.content_version}"
            raw = read_bytes(
                Path(root).resolve(), f"{version}/release.json", MAX_RECORD_BYTES
            )
            record = ReleaseRecord.model_validate(parse_document(raw))
            if purpose == "participant" and (
                record.reviewed_by == "automated test fixture only"
                or any(
                    "test-only" in item.license_evidence.casefold()
                    for item in record.media
                )
            ):
                raise ValueError
            sealed[version] = hashlib.sha256(raw).hexdigest()
        if signed != {"purpose": purpose, "releases": sealed}:
            raise ValueError
    except (OSError, ValueError, RuntimeError):
        raise PlaytestConfigurationError(
            "Playtest deployment requires a nonempty, approved release catalog for its purpose"
        ) from None


def create_playtest_app(
    environ: Mapping[str, str] | None = None,
    *,
    test_publication_store: PublicationStore | None = None,
):
    """Build a Playtest app, with explicit Python-only publication injection for tests."""
    env = os.environ if environ is None else environ
    secret, target = _playtest_settings(env)
    origins = validate_origins(env.get("TWOWORLDS_ALLOWED_ORIGINS", ""))
    if any(not origin.startswith("https://") for origin in origins):
        raise PlaytestConfigurationError("Playtest requires exact HTTPS origins")

    root = env.get("TWOWORLDS_PLAYTEST_PUBLICATION_ROOT")
    if test_publication_store is None and not root:
        raise PlaytestConfigurationError(
            "An explicit Playtest publication store is required"
        )
    try:
        store = (
            test_publication_store
            if test_publication_store is not None
            else PublicationStore(Path(root))
        )
        catalog = store.catalog()
    except Exception:
        raise PlaytestConfigurationError(
            "Playtest publication store failed validation"
        ) from None
    if test_publication_store is None:
        _validate_deployment_approval(env, root, catalog)

    repository = _connect_mongo(target)
    try:
        return create_app(
            repository=repository,
            ai_mode="demo",
            allowed_origins=origins,
            publication_store=store,
            email_sender=DisabledEmailCodeSender(),
            verification_secret=secret,
            cookie_secure=True,
            enable_email_account_routes=False,
        )
    except Exception:
        repository.close()
        raise PlaytestConfigurationError("Playtest application setup failed") from None


def _launch_app():
    try:
        return create_playtest_app()
    except PlaytestConfigurationError as error:
        # Uvicorn drops raw exception text through ServerLogFilter.
        # These configuration messages contain only fixed operator guidance.
        print(str(error), file=sys.stderr)
        raise


def main() -> int:
    import uvicorn

    try:
        port = int(os.environ.get("TWOWORLDS_PORT", "8000"))
        if not 1 <= port <= 65535:
            raise ValueError
        proxy_ip = trusted_proxy_ip(os.environ.get("TWOWORLDS_TRUSTED_PROXY_IP", ""))
        log_config = deepcopy(uvicorn.config.LOGGING_CONFIG)
        log_config["filters"] = {"safe_server": {"()": ServerLogFilter}}
        log_config["handlers"]["default"]["filters"] = ["safe_server"]
        uvicorn.run(
            "twoworlds.playtest:_launch_app",
            factory=True,
            host=os.environ.get("TWOWORLDS_HOST", "127.0.0.1"),
            port=port,
            access_log=False,
            proxy_headers=bool(proxy_ip),
            forwarded_allow_ips=proxy_ip,
            log_config=log_config,
            server_header=False,
            ws="websockets-sansio",
            ws_max_size=MAX_CLIENT_MESSAGE_BYTES,
            ws_ping_interval=None,
            ws_per_message_deflate=False,
        )
        return 0
    except Exception:
        print(
            "Playtest startup failed. Check storage, origin, secret, publication and listener settings.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
