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


@pytest.fixture
def production_env():
    return {
        "TWOWORLDS_MODE": "production",
        "TWOWORLDS_STORAGE_BACKEND": "mongo",
        "TWOWORLDS_ALLOWED_ORIGINS": PROD_ORIGIN,
        "TWOWORLDS_EMAIL_MODE": "smtp",
        "TWOWORLDS_VERIFICATION_SECRET": "durable_production_secret_32chars!",
        "MONGO_URI": "mongodb://127.0.0.1:27017",
        "MONGO_DATABASE": "twoworlds",
        "SMTP_HOST": "mail.example.invalid",
        "SMTP_PORT": "587",
        "SMTP_FROM": "noreply@example.invalid",
        "SMTP_USERNAME": "test_smtp_user",
        "SMTP_PASSWORD": "test_smtp_password",
    }


def test_production_mode_rejects_sqlite_backend(production_env):
    production_env["TWOWORLDS_STORAGE_BACKEND"] = "sqlite"
    with pytest.raises(
        ValueError, match="Production mode requires TWOWORLDS_STORAGE_BACKEND=mongo"
    ):
        create_server_app(production_env)


def test_production_mode_requires_mongo_uri_and_database(production_env):
    del production_env["MONGO_URI"]
    del production_env["MONGO_DATABASE"]
    with pytest.raises(ValueError, match="requires MONGO_URI and MONGO_DATABASE"):
        create_server_app(production_env)


def test_production_mode_requires_durable_verification_secret(production_env):
    production_env["TWOWORLDS_VERIFICATION_SECRET"] = "short"
    with pytest.raises(
        ValueError, match="explicit durable TWOWORLDS_VERIFICATION_SECRET"
    ):
        create_server_app(production_env)


def test_production_mode_fails_cleanly_when_mongo_unreachable(production_env, tmp_path):
    production_env["MONGO_URI"] = (
        "mongodb://127.0.0.1:59999/?serverSelectionTimeoutMS=500"
    )
    production_env["TWOWORLDS_SQLITE_PATH"] = str(tmp_path / "fallback.sqlite")
    with pytest.raises(
        ConnectionError,
        match="Production MongoDB connection failed; server will not start",
    ):
        create_server_app(production_env)
    assert not (tmp_path / "fallback.sqlite").exists()


def test_production_mode_succeeds_with_mongo(production_env, mongo_database):
    database, uri = mongo_database
    production_env.update(MONGO_URI=uri, MONGO_DATABASE=database.name)
    app = create_server_app(production_env)
    with TestClient(app) as client:
        res = client.get("/api/scripts")
        assert res.status_code == 200
        assert res.json() == []


def test_production_mode_rejects_invalid_ai_mode(production_env):
    production_env["TWOWORLDS_AI_MODE"] = "unknown_ai_mode"
    with pytest.raises(ValueError, match="Invalid TWOWORLDS_AI_MODE"):
        create_server_app(production_env)


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
# SMTP Email Mode Validation & Error Sanitization
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("server_mode", ["production", "formal"])
@pytest.mark.parametrize("email_mode", ["console", "", "invalid", None])
def test_production_rejects_non_smtp_email_mode(
    production_env, server_mode, email_mode, monkeypatch
):
    from twoworlds.security import mailer
    from twoworlds.storage import mongo

    production_env["TWOWORLDS_MODE"] = server_mode
    if email_mode is None:
        del production_env["TWOWORLDS_EMAIL_MODE"]
    else:
        production_env["TWOWORLDS_EMAIL_MODE"] = email_mode

    def unexpected_setup(*args, **kwargs):
        pytest.fail("Invalid email mode must fail before initializing email or MongoDB")

    monkeypatch.setattr(mailer, "build_email_sender", unexpected_setup)
    monkeypatch.setattr(mongo, "MongoRepository", unexpected_setup)
    with pytest.raises(
        ValueError, match="Production mode requires TWOWORLDS_EMAIL_MODE=smtp"
    ):
        create_server_app(production_env)


@pytest.mark.parametrize("field", ["SMTP_HOST", "SMTP_FROM"])
def test_production_smtp_mode_requires_host_and_from(production_env, field):
    del production_env[field]
    with pytest.raises(
        ValueError, match="Explicit SMTP host, port and from address required"
    ):
        create_server_app(production_env)


@pytest.mark.parametrize(
    ("port", "message"),
    [
        ("invalid", "SMTP port must be an integer"),
        ("0", "Explicit SMTP host, port and from address required"),
        ("65536", "Explicit SMTP host, port and from address required"),
    ],
)
def test_production_smtp_mode_rejects_invalid_port(production_env, port, message):
    production_env["SMTP_PORT"] = port
    with pytest.raises(ValueError, match=message):
        create_server_app(production_env)


def test_production_smtp_mode_rejects_username_without_password(production_env):
    del production_env["SMTP_PASSWORD"]
    with pytest.raises(ValueError, match="SMTP password required when username is set"):
        create_server_app(production_env)


@pytest.mark.parametrize("server_mode", ["production", "formal"])
def test_production_smtp_mode_accepts_all_valid_smtp_config(
    production_env, server_mode, mongo_database, monkeypatch
):
    from twoworlds.security import mailer

    database, uri = mongo_database
    production_env.update(
        TWOWORLDS_MODE=server_mode, MONGO_URI=uri, MONGO_DATABASE=database.name
    )

    def unexpected_smtp_connection(*args, **kwargs):
        pytest.fail("Configuration validation must never connect to an SMTP server")

    monkeypatch.setattr(mailer.smtplib, "SMTP", unexpected_smtp_connection)
    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", unexpected_smtp_connection)
    with TestClient(create_server_app(production_env)) as client:
        assert isinstance(client.app.state.email_sender, mailer.SmtpEmailCodeSender)
        assert client.get("/api/scripts").status_code == 200


def test_demo_mode_console_email_unaffected_by_smtp_compose_default(tmp_path):
    """5. Demo 模式仍然可以显式使用 console，不需要 SMTP 配置。"""
    from twoworlds.security.mailer import ConsoleEmailCodeSender

    db_path = tmp_path / "demo.sqlite"
    env = {
        "TWOWORLDS_MODE": "demo",
        "TWOWORLDS_STORAGE_BACKEND": "sqlite",
        "TWOWORLDS_SQLITE_PATH": str(db_path),
        "TWOWORLDS_ALLOWED_ORIGINS": PROD_ORIGIN,
        "TWOWORLDS_EMAIL_MODE": "console",
        # No SMTP_* vars — console mode must not require them
    }
    with TestClient(create_server_app(env)) as client:
        assert isinstance(client.app.state.email_sender, ConsoleEmailCodeSender)
        assert client.get("/api/scripts").status_code == 200
    assert db_path.is_file()


def test_smtp_sender_error_sanitization_does_not_leak_credentials_or_code(
    monkeypatch, caplog
):
    """SMTP 错误脱敏测试：
    - SMTP 发送异常不会泄露 SMTP_PASSWORD。
    - 不会泄露验证码。
    - 不会泄露 SMTP 连接异常详情。
    - 上层日志不会记录邮箱和验证码。
    """
    import smtplib

    from twoworlds.application.verification import CodeDelivery
    from twoworlds.ports.email import EmailSendError
    from twoworlds.security.mailer import SmtpEmailCodeSender

    test_password = "leak-check-password-secret-xyz"
    test_code = "729401"
    test_email = "target-user@example.com"
    raw_smtp_error = "535 5.7.8 Credentials rejected with session 0xDEADBEEF"

    class FaultySMTP:
        def __init__(self, *args, **kwargs):
            pass

        def ehlo(self):
            pass

        def starttls(self, *args, **kwargs):
            pass

        def login(self, user, password):
            raise smtplib.SMTPAuthenticationError(535, raw_smtp_error)

        def quit(self):
            pass

    monkeypatch.setattr(smtplib, "SMTP", FaultySMTP)

    sender = SmtpEmailCodeSender(
        host="mail.example.com",
        port=587,
        username="smtp_user",
        password=test_password,
        sender="noreply@example.com",
    )

    # 1. 验证直接调用 SmtpEmailCodeSender 产生的异常信息与堆栈被彻底脱敏
    with pytest.raises(EmailSendError) as exc_info:
        sender.send_code(test_email, "register", test_code)

    err = exc_info.value
    err_text = str(err)
    # 消息严格标准化，绝不向上传播底层详细堆栈
    assert err_text == "Verification email delivery failed"
    # 原因链被 from None 显式压制
    assert err.__cause__ is None
    assert err.__suppress_context__ is True
    # 密码、验证码、底层异常细节绝对不出现在异常描述中
    assert test_password not in err_text
    assert test_code not in err_text
    assert raw_smtp_error not in err_text
    assert test_email not in err_text

    # 2. 验证结合 CodeDelivery 异步处理层时，日志脱敏且正确执行 on_failure 回调
    delivery = CodeDelivery(sender, max_workers=1)
    failed = []
    delivery.submit(
        test_email,
        "register",
        test_code,
        on_failure=lambda: failed.append(True),
    )
    assert delivery.wait(timeout=5)
    delivery.close()

    assert len(failed) == 1
    # 检查全局日志：绝无密码、验证码、邮箱及底层 SMTP 报错明细
    assert test_password not in caplog.text
    assert test_code not in caplog.text
    assert test_email not in caplog.text
    assert raw_smtp_error not in caplog.text
    assert "Verification email delivery failed (purpose=register)" in caplog.text
