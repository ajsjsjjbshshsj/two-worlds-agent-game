"""Tests for the production and container application launcher (twoworlds.server)."""

from fastapi.testclient import TestClient
import pytest

from twoworlds.server import create_server_app, main, validate_origins

PROD_ORIGIN = "http://localhost:8080"


def test_validate_origins_accepts_clean_http_and_https():
    origins = validate_origins("http://localhost:8080, https://twoworlds.app")
    assert origins == ("http://localhost:8080", "https://twoworlds.app")


@pytest.mark.parametrize(
    "bad_origin",
    [
        "",
        "*",
        "http://localhost:8080/",
        "https://user:pass@example.com",
        "https://example.com/api",
        "https://example.com?query=1",
        "https://example.com#hash",
        "ftp://example.com",
    ],
)
def test_validate_origins_rejects_malformed_or_wildcard(bad_origin):
    with pytest.raises(ValueError):
        validate_origins(bad_origin)


def test_missing_or_invalid_mode_raises():
    with pytest.raises(ValueError, match="Explicit TWOWORLDS_MODE required"):
        create_server_app({})

    with pytest.raises(ValueError, match="Explicit TWOWORLDS_MODE required"):
        create_server_app({"TWOWORLDS_MODE": "invalid_mode"})


# ---------------------------------------------------------------------------
# Production Mode Validation
# ---------------------------------------------------------------------------


def test_production_mode_rejects_sqlite_backend():
    env = {
        "TWOWORLDS_MODE": "production",
        "TWOWORLDS_STORAGE_BACKEND": "sqlite",
        "TWOWORLDS_ALLOWED_ORIGINS": PROD_ORIGIN,
        "TWOWORLDS_EMAIL_MODE": "console",
        "TWOWORLDS_VERIFICATION_SECRET": "durable_production_secret_32chars!",
        "MONGO_URI": "mongodb://127.0.0.1:27017",
        "MONGO_DATABASE": "twoworlds",
    }
    with pytest.raises(
        ValueError, match="Production mode requires TWOWORLDS_STORAGE_BACKEND=mongo"
    ):
        create_server_app(env)


def test_production_mode_requires_mongo_uri_and_database():
    env = {
        "TWOWORLDS_MODE": "production",
        "TWOWORLDS_STORAGE_BACKEND": "mongo",
        "TWOWORLDS_ALLOWED_ORIGINS": PROD_ORIGIN,
        "TWOWORLDS_EMAIL_MODE": "console",
        "TWOWORLDS_VERIFICATION_SECRET": "durable_production_secret_32chars!",
    }
    with pytest.raises(ValueError, match="requires MONGO_URI and MONGO_DATABASE"):
        create_server_app(env)


def test_production_mode_requires_durable_verification_secret():
    env = {
        "TWOWORLDS_MODE": "production",
        "TWOWORLDS_STORAGE_BACKEND": "mongo",
        "TWOWORLDS_ALLOWED_ORIGINS": PROD_ORIGIN,
        "TWOWORLDS_EMAIL_MODE": "console",
        "MONGO_URI": "mongodb://127.0.0.1:27017",
        "MONGO_DATABASE": "twoworlds",
        "TWOWORLDS_VERIFICATION_SECRET": "short",
    }
    with pytest.raises(
        ValueError, match="explicit durable TWOWORLDS_VERIFICATION_SECRET"
    ):
        create_server_app(env)


def test_production_mode_fails_cleanly_when_mongo_unreachable(tmp_path):
    env = {
        "TWOWORLDS_MODE": "production",
        "TWOWORLDS_STORAGE_BACKEND": "mongo",
        "TWOWORLDS_ALLOWED_ORIGINS": PROD_ORIGIN,
        "TWOWORLDS_EMAIL_MODE": "console",
        "TWOWORLDS_VERIFICATION_SECRET": "durable_production_secret_32chars!",
        # Use an invalid unreachable port
        "MONGO_URI": "mongodb://127.0.0.1:59999/?serverSelectionTimeoutMS=500",
        "MONGO_DATABASE": "twoworlds",
        # Provide sqlite path to prove it NEVER falls back to sqlite!
        "TWOWORLDS_SQLITE_PATH": str(tmp_path / "fallback.sqlite"),
    }
    with pytest.raises(
        ConnectionError,
        match="Production MongoDB connection failed; server will not start",
    ):
        create_server_app(env)
    assert not (tmp_path / "fallback.sqlite").exists()


def test_production_mode_succeeds_with_mongo(mongo_database):
    database, uri = mongo_database
    env = {
        "TWOWORLDS_MODE": "production",
        "TWOWORLDS_STORAGE_BACKEND": "mongo",
        "TWOWORLDS_ALLOWED_ORIGINS": PROD_ORIGIN,
        "TWOWORLDS_EMAIL_MODE": "console",
        "TWOWORLDS_VERIFICATION_SECRET": "durable_production_secret_32chars!",
        "MONGO_URI": uri,
        "MONGO_DATABASE": database.name,
    }
    app = create_server_app(env)
    with TestClient(app) as client:
        res = client.get("/api/scripts")
        assert res.status_code == 200
        assert res.json() == []


def test_production_mode_rejects_invalid_ai_mode():
    env = {
        "TWOWORLDS_MODE": "production",
        "TWOWORLDS_STORAGE_BACKEND": "mongo",
        "TWOWORLDS_ALLOWED_ORIGINS": PROD_ORIGIN,
        "TWOWORLDS_EMAIL_MODE": "console",
        "TWOWORLDS_VERIFICATION_SECRET": "durable_production_secret_32chars!",
        "MONGO_URI": "mongodb://127.0.0.1:27017",
        "MONGO_DATABASE": "twoworlds",
        "TWOWORLDS_AI_MODE": "unknown_ai_mode",
    }
    with pytest.raises(ValueError, match="Invalid TWOWORLDS_AI_MODE"):
        create_server_app(env)


# ---------------------------------------------------------------------------
# Demo Mode Validation
# ---------------------------------------------------------------------------


def test_demo_mode_rejects_mongo_backend(tmp_path):
    env = {
        "TWOWORLDS_MODE": "demo",
        "TWOWORLDS_STORAGE_BACKEND": "mongo",
        "TWOWORLDS_ALLOWED_ORIGINS": PROD_ORIGIN,
        "TWOWORLDS_SQLITE_PATH": str(tmp_path / "demo.sqlite"),
        "TWOWORLDS_EMAIL_MODE": "console",
    }
    with pytest.raises(
        ValueError, match="Demo mode requires TWOWORLDS_STORAGE_BACKEND=sqlite"
    ):
        create_server_app(env)


def test_demo_mode_requires_sqlite_path():
    env = {
        "TWOWORLDS_MODE": "demo",
        "TWOWORLDS_STORAGE_BACKEND": "sqlite",
        "TWOWORLDS_ALLOWED_ORIGINS": PROD_ORIGIN,
        "TWOWORLDS_EMAIL_MODE": "console",
    }
    with pytest.raises(ValueError, match="Demo mode requires TWOWORLDS_SQLITE_PATH"):
        create_server_app(env)


def test_demo_mode_forbids_external_ai_provider(tmp_path):
    env = {
        "TWOWORLDS_MODE": "demo",
        "TWOWORLDS_STORAGE_BACKEND": "sqlite",
        "TWOWORLDS_SQLITE_PATH": str(tmp_path / "demo.sqlite"),
        "TWOWORLDS_ALLOWED_ORIGINS": PROD_ORIGIN,
        "TWOWORLDS_EMAIL_MODE": "console",
        "TWOWORLDS_AI_MODE": "provider",
    }
    with pytest.raises(ValueError, match="Demo mode forbids external AI provider"):
        create_server_app(env)


def test_demo_mode_succeeds_with_sqlite_and_persists(tmp_path):
    db_path = tmp_path / "demo.sqlite"
    env = {
        "TWOWORLDS_MODE": "demo",
        "TWOWORLDS_STORAGE_BACKEND": "sqlite",
        "TWOWORLDS_SQLITE_PATH": str(db_path),
        "TWOWORLDS_ALLOWED_ORIGINS": PROD_ORIGIN,
        "TWOWORLDS_EMAIL_MODE": "console",
    }
    app = create_server_app(env)
    with TestClient(app) as client:
        res = client.get("/api/scripts")
        assert res.status_code == 200
        assert res.json() == []
    assert db_path.exists()


# ---------------------------------------------------------------------------
# CLI & Process Startup
# ---------------------------------------------------------------------------


def test_main_cli_fails_gracefully_with_bad_env(monkeypatch, capsys):
    monkeypatch.setenv("TWOWORLDS_MODE", "invalid")
    exit_code = main()
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "Server startup failed" in captured.err


def test_main_cli_parses_host_and_port(tmp_path, monkeypatch):
    import uvicorn

    recorded = {}
    monkeypatch.setenv("TWOWORLDS_MODE", "demo")
    monkeypatch.setenv("TWOWORLDS_STORAGE_BACKEND", "sqlite")
    monkeypatch.setenv("TWOWORLDS_SQLITE_PATH", str(tmp_path / "demo.sqlite"))
    monkeypatch.setenv("TWOWORLDS_ALLOWED_ORIGINS", PROD_ORIGIN)
    monkeypatch.setenv("TWOWORLDS_EMAIL_MODE", "console")
    monkeypatch.setenv("TWOWORLDS_HOST", "0.0.0.0")
    monkeypatch.setenv("TWOWORLDS_PORT", "8888")

    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: recorded.update(kwargs))
    exit_code = main()
    assert exit_code == 0
    assert recorded["host"] == "0.0.0.0"
    assert recorded["port"] == 8888
    assert recorded["proxy_headers"] is True
    assert recorded["server_header"] is False


# ---------------------------------------------------------------------------
# SMTP Email Mode Validation (compose.yml production default = smtp)
# ---------------------------------------------------------------------------


def test_production_smtp_mode_rejects_missing_smtp_host():
    """Production + TWOWORLDS_EMAIL_MODE=smtp must reject when SMTP_HOST is absent.

    This is the key guard for compose.yml defaulting to smtp: without SMTP_HOST
    and SMTP_FROM the backend refuses to start rather than silently using no-op email.
    """
    env = {
        "TWOWORLDS_MODE": "production",
        "TWOWORLDS_STORAGE_BACKEND": "mongo",
        "TWOWORLDS_ALLOWED_ORIGINS": PROD_ORIGIN,
        "TWOWORLDS_EMAIL_MODE": "smtp",
        "TWOWORLDS_VERIFICATION_SECRET": "durable_production_secret_32chars!",
        "MONGO_URI": "mongodb://127.0.0.1:27017",
        "MONGO_DATABASE": "twoworlds",
        # SMTP_HOST and SMTP_FROM intentionally omitted
    }
    with pytest.raises(ValueError, match="SMTP"):
        create_server_app(env)


def test_production_smtp_mode_accepts_full_smtp_config(mongo_database):
    """Production + smtp + complete SMTP config must pass email validation.

    Uses a fake SMTP host — no real connection is made during app construction.
    """
    database, uri = mongo_database
    env = {
        "TWOWORLDS_MODE": "production",
        "TWOWORLDS_STORAGE_BACKEND": "mongo",
        "TWOWORLDS_ALLOWED_ORIGINS": PROD_ORIGIN,
        "TWOWORLDS_EMAIL_MODE": "smtp",
        "TWOWORLDS_VERIFICATION_SECRET": "durable_production_secret_32chars!",
        "MONGO_URI": uri,
        "MONGO_DATABASE": database.name,
        # Minimal valid SMTP config (no password required when no username set)
        "SMTP_HOST": "mail.example.com",
        "SMTP_PORT": "587",
        "SMTP_FROM": "noreply@example.com",
    }
    # Should not raise — email sender is validated at construction, not at send time
    app = create_server_app(env)
    assert app is not None


def test_demo_mode_console_email_unaffected_by_smtp_compose_default(tmp_path):
    """Demo mode with explicit console email must succeed without any SMTP_* vars.

    compose.demo.yml keeps TWOWORLDS_EMAIL_MODE=console so this path is safe.
    """
    db_path = tmp_path / "demo.sqlite"
    env = {
        "TWOWORLDS_MODE": "demo",
        "TWOWORLDS_STORAGE_BACKEND": "sqlite",
        "TWOWORLDS_SQLITE_PATH": str(db_path),
        "TWOWORLDS_ALLOWED_ORIGINS": PROD_ORIGIN,
        "TWOWORLDS_EMAIL_MODE": "console",
        # No SMTP_* vars — console mode must not require them
    }
    app = create_server_app(env)
    assert app is not None
