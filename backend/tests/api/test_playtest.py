"""Playtest contracts against isolated real MongoDB processes."""

from collections import UserDict
from hashlib import sha256
import json
import os
import secrets
import socket
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
import httpx
from pymongo import MongoClient
import pytest

from tests.contracts.support import Identity, Platform, error, ok
from tests.mongodb_recovery import mongo_node
from tests.save_support import make_publications
from twoworlds import playtest
from twoworlds.application.dialogue import DEMO_ANSWER
from twoworlds.content.publication import PublicationStore
from twoworlds.ports.email import EmailSendError
from twoworlds.ports.repository import RepositoryError
from twoworlds.security import mailer

ORIGIN = "https://playtest.invalid"
PASSWORD = "test account password 9"
URI = "TWOWORLDS_PLAYTEST_MONGO_URI"
DATABASE = "TWOWORLDS_PLAYTEST_MONGO_DATABASE"
SECRET = "TWOWORLDS_PLAYTEST_VERIFICATION_SECRET"
PUBLICATIONS = "TWOWORLDS_PLAYTEST_PUBLICATION_ROOT"
APPROVAL = "TWOWORLDS_PLAYTEST_APPROVAL_FILE"
PURPOSE = "TWOWORLDS_PLAYTEST_CONTENT_PURPOSE"


@pytest.fixture
def settings():
    name = "twoworlds_playtest_" + uuid4().hex
    return {
        "TWOWORLDS_MODE": "playtest",
        "TWOWORLDS_ALLOWED_ORIGINS": ORIGIN,
        URI: f"mongodb://test_user:fixture-secret@127.0.0.1:27017/{name}",
        DATABASE: name,
        SECRET: secrets.token_hex(32),
    }


@pytest.fixture
def publications(tmp_path):
    store, publish = make_publications(tmp_path)
    publish()
    publish(identifier="starline")
    return store, tmp_path / "releases"


@pytest.fixture
def deployment_settings(publications, tmp_path):
    store, root = publications
    manifest = tmp_path / "approval.json"
    manifest.write_text(
        json.dumps(
            {
                "purpose": "internal-drill",
                "releases": {
                    f"{script.id}/{script.content_version}": sha256(
                        (
                            root / script.id / script.content_version / "release.json"
                        ).read_bytes()
                    ).hexdigest()
                    for script in store.catalog()
                },
            }
        ),
        encoding="utf-8",
    )
    return {PUBLICATIONS: str(root), APPROVAL: str(manifest), PURPOSE: "internal-drill"}


@pytest.fixture(scope="module")
def authenticated_mongo():
    with TemporaryDirectory(prefix="tw-playtest-auth-") as folder:
        with mongo_node(Path(folder) / "mongo") as node:
            yield node


@pytest.fixture
def connected(settings, authenticated_mongo):
    name = settings[DATABASE]
    authenticated_mongo.provision(name, "playtest_app", "readWrite")
    return settings | {URI: authenticated_mongo.uri("playtest_app", name)}


@pytest.mark.parametrize("required", [URI, DATABASE, SECRET])
def test_does_not_inherit_production_connection_or_secret(
    settings, required, monkeypatch
):
    del settings[required]
    settings.update(
        MONGO_URI="mongodb://production.invalid",
        MONGO_DATABASE="twoworlds",
        TWOWORLDS_VERIFICATION_SECRET=secrets.token_hex(32),
    )
    monkeypatch.setattr(playtest, "MongoRepository", forbidden)
    with pytest.raises(ValueError, match=required):
        playtest.create_playtest_app(settings)


def forbidden(*_args, **_options):
    pytest.fail("Disabled integration or unexpected repository connection")


@pytest.mark.parametrize(
    ("name", "value", "message"),
    [
        ("TWOWORLDS_MODE", "production", "MODE=playtest"),
        ("TWOWORLDS_AI_MODE", "provider", "AI_MODE=demo"),
        ("TWOWORLDS_EMAIL_MODE", "console", "EMAIL_MODE=disabled"),
        ("TWOWORLDS_EMAIL_MODE", "smtp", "EMAIL_MODE=disabled"),
        ("TWOWORLDS_STORAGE_BACKEND", "sqlite", "requires MongoDB"),
        ("TWOWORLDS_ALLOWED_ORIGINS", "http://playtest.invalid", "exact HTTPS"),
        ("TWOWORLDS_ALLOWED_ORIGINS", "https://*.invalid", "exact HTTP/HTTPS"),
        ("TWOWORLDS_ALLOWED_ORIGINS", ORIGIN + "/api", "exact HTTP/HTTPS"),
        (SECRET, "", "32 random bytes"),
        (SECRET, "twoworlds-demo-verification-secret-32chars", "32 random bytes"),
        (SECRET, "deadbeef" * 8, "32 random bytes"),
        (SECRET, bytes(range(32)).hex(), "32 random bytes"),
        (DATABASE, "twoworlds", "dedicated twoworlds_playtest_"),
        (URI, "mongodb://127.0.0.1/test", "database-scoped SCRAM"),
        (URI, "mongodb://user:secret@127.0.0.1/twoworlds", "database-scoped SCRAM"),
        (URI, "mongodb+srv://user:secret@production.invalid", "database-scoped SCRAM"),
    ],
)
def test_invalid_config_fails_before_connecting(
    settings, monkeypatch, name, value, message
):
    settings[name] = value
    monkeypatch.setattr(playtest, "MongoRepository", forbidden)
    with pytest.raises(ValueError, match=message):
        playtest.create_playtest_app(settings)


def test_requires_explicit_sealed_publications(settings, publications, monkeypatch):
    monkeypatch.setattr(playtest, "MongoRepository", forbidden)
    with pytest.raises(ValueError, match="explicit Playtest publication store"):
        playtest.create_playtest_app(settings)

    store, root = publications
    manifest = root / "lighthouse" / "1.0.0" / "release.json"
    manifest.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="publication store failed validation"):
        playtest.create_playtest_app(settings, test_publication_store=store)


@pytest.mark.parametrize("missing", [(APPROVAL,), (PURPOSE,), (APPROVAL, PURPOSE)])
def test_launch_app_requires_explicit_deployment_approval(
    settings, deployment_settings, monkeypatch, missing
):
    for field, value in (settings | deployment_settings).items():
        monkeypatch.setenv(field, value)
    for field in missing:
        monkeypatch.delenv(field)
    monkeypatch.setattr(playtest, "MongoRepository", forbidden)

    with pytest.raises(
        playtest.PlaytestConfigurationError, match="APPROVAL_FILE.*CONTENT_PURPOSE"
    ):
        playtest._launch_app()


@pytest.mark.parametrize(
    "invalid",
    [
        "missing-file",
        "empty-catalog",
        "invalid-json",
        "version-mismatch",
        "sha256-mismatch",
        "unknown-purpose",
        "test-only-media",
    ],
)
def test_launch_app_rejects_invalid_deployment_approval_before_mongo(
    settings, deployment_settings, tmp_path, monkeypatch, invalid
):
    manifest = Path(deployment_settings[APPROVAL])
    approval = json.loads(manifest.read_text(encoding="utf-8"))
    reference = "lighthouse/1.0.0"
    if invalid == "missing-file":
        manifest.unlink()
    elif invalid == "empty-catalog":
        root = tmp_path / "empty"
        PublicationStore.initialize(root)
        deployment_settings[PUBLICATIONS] = str(root)
        approval["releases"] = {}
    elif invalid == "invalid-json":
        manifest.write_text("{", encoding="utf-8")
    elif invalid == "version-mismatch":
        approval["releases"]["lighthouse/9.9.9"] = approval["releases"].pop(reference)
    elif invalid == "sha256-mismatch":
        approval["releases"][reference] = "0" * 64
    elif invalid == "unknown-purpose":
        approval["purpose"] = deployment_settings[PURPOSE] = "unknown-purpose"
    elif invalid == "test-only-media":
        approval["purpose"] = deployment_settings[PURPOSE] = "participant"
        for version in approval["releases"]:
            seal = Path(deployment_settings[PUBLICATIONS]) / version / "release.json"
            record = json.loads(seal.read_text(encoding="utf-8"))
            # Keep the media markers and pin the changed record in the manifest.
            record["reviewed_by"] = "Synthetic review fixture"
            sealed = json.dumps(record).encode()
            seal.write_bytes(sealed)
            approval["releases"][version] = sha256(sealed).hexdigest()
    if invalid not in {"missing-file", "invalid-json"}:
        manifest.write_text(json.dumps(approval), encoding="utf-8")
    for field, value in (settings | deployment_settings).items():
        monkeypatch.setenv(field, value)
    monkeypatch.setattr(playtest, "MongoRepository", forbidden)

    with pytest.raises(
        playtest.PlaytestConfigurationError, match="nonempty, approved release catalog"
    ):
        playtest._launch_app()


def test_bad_ca_file_does_not_disclose_the_path(settings, tmp_path, monkeypatch):
    from urllib.parse import urlencode

    marker = "private-ca-filename"
    settings[URI] += "?" + urlencode({"tls": "true", "tlsCAFile": tmp_path / marker})
    monkeypatch.setattr(playtest, "MongoRepository", forbidden)
    with pytest.raises(ValueError, match="database-scoped SCRAM") as caught:
        playtest.create_playtest_app(settings)
    assert marker not in str(caught.value) and caught.value.__suppress_context__


def test_no_auth_server_is_rejected_before_index_creation(settings, publications):
    store, _ = publications
    with TemporaryDirectory(prefix="tw-playtest-noauth-") as folder:
        with mongo_node(Path(folder) / "mongo", authenticated=False) as node:
            name = settings[DATABASE]
            node.provision(name, "playtest_app", "readWrite")
            settings[URI] = node.uri("playtest_app", name)
            # This Mongo accepts the credentials but also allows anonymous reads.
            with MongoClient(settings[URI]) as client:
                auth = client.admin.command("connectionStatus")["authInfo"]
                assert auth["authenticatedUsers"] == [
                    {"user": "playtest_app", "db": name}
                ]
            with pytest.raises(
                ValueError, match="not an isolated authenticated database"
            ):
                playtest.create_playtest_app(settings, test_publication_store=store)
            assert node.admin[name].list_collection_names() == []


def test_cross_database_privileges_are_rejected(
    connected, publications, authenticated_mongo
):
    name = connected[DATABASE]
    authenticated_mongo.admin[name].command(
        "updateUser",
        "playtest_app",
        roles=["readWrite", {"role": "read", "db": "twoworlds"}],
    )
    with pytest.raises(ValueError, match="not an isolated authenticated database"):
        playtest.create_playtest_app(connected, test_publication_store=publications[0])
    assert authenticated_mongo.admin[name].list_collection_names() == []


def test_database_failure_is_sanitized(settings, publications, capsys):
    name = settings[DATABASE]
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        settings[URI] = (
            f"mongodb://fixture-user:unreachable-credential@127.0.0.1:{reserved.getsockname()[1]}/{name}"
        )
        with pytest.raises(ValueError, match="Playtest MongoDB unavailable") as caught:
            playtest.create_playtest_app(
                settings, test_publication_store=publications[0]
            )
    messages = capsys.readouterr()
    assert (
        "unreachable-credential" not in str(caught.value) + messages.out + messages.err
    )
    assert caught.value.__suppress_context__


def test_closed_routes_and_mail_adapter(
    connected, publications, authenticated_mongo, monkeypatch, capsys
):
    monkeypatch.setattr(mailer.ConsoleEmailCodeSender, "send_code", forbidden)
    monkeypatch.setattr(mailer.smtplib, "SMTP", forbidden)
    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", forbidden)
    app = playtest.create_playtest_app(
        connected, test_publication_store=publications[0]
    )
    with TestClient(app, base_url=ORIGIN) as client:
        for path, payload in {
            "/api/accounts": {
                "password": PASSWORD,
                "display_name": "Synthetic",
                "code": "123456",
            },
            "/api/verification-codes": {"purpose": "register"},
            "/api/password-resets": {"new_password": PASSWORD, "code": "123456"},
        }.items():
            response = client.post(
                path,
                json=payload | {"email": "recipient@example.invalid"},
                headers={"Origin": ORIGIN},
            )
            assert response.status_code == 404
            assert path not in app.openapi()["paths"]
        assert app.state.verification_service is None
        with pytest.raises(EmailSendError, match="^Verification email is disabled$"):
            app.state.email_sender.send_code(
                "recipient@example.invalid", "register", "123456"
            )
    db = authenticated_mongo.admin[connected[DATABASE]]
    assert (
        db.verification_codes.count_documents({})
        == db.accounts.count_documents({})
        == 0
    )
    assert capsys.readouterr() == ("", "")


class Player(Identity):
    @property
    def headers(self):
        return super().headers | {"Origin": ORIGIN}


def login(client, email):
    response = client.post(
        "/api/sessions",
        json={"email": email, "password": PASSWORD},
        headers={"Origin": ORIGIN},
    )
    account_id = ok(response)["account"]["id"]
    token = response.cookies.get("tw_session")
    assert token and token not in response.text
    flags = response.headers["set-cookie"].lower().split("; ")
    assert {"secure", "httponly", "samesite=lax"} <= set(flags)
    assert response.headers["cache-control"] == "no-store"
    return Player(account_id, email, PASSWORD, token)


def test_login_logout_verified_games_demo_and_repository_cleanup(
    connected, publications, monkeypatch
):
    class RuntimeEnv(UserDict):
        def __getitem__(self, key):
            if key == "TWOWORLDS_AI_API_KEY" or key.startswith("SMTP_"):
                forbidden()
            return super().__getitem__(key)

    repositories = []
    real_repository = playtest.MongoRepository

    def track(*args, **kwargs):
        repository = real_repository(*args, **kwargs)
        repositories.append(repository)
        return repository

    monkeypatch.setattr(playtest, "MongoRepository", track)
    env = RuntimeEnv(connected | {"TWOWORLDS_COOKIE_SECURE": "0"})
    app = playtest.create_playtest_app(env, test_publication_store=publications[0])
    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get("/health/ready").status_code == 200
        scripts = ok(client.get("/api/scripts"))
        assert [(script["id"], script["content_version"]) for script in scripts] == [
            ("lighthouse", "1.0.0"),
            ("starline", "1.0.0"),
        ]
        emails = ["a@example.invalid", "b@example.invalid"]
        identity = app.state.identity_service
        for email in emails:
            # Test-only setup with the existing service. No public enrollment route.
            identity.revoke(identity.register(email, PASSWORD, "Synthetic").token)
        a, b = (login(client, email) for email in emails)
        assert (
            ok(client.get("/api/me", headers=a.headers))["account"]["id"]
            == a.account_id
        )
        assert (
            ok(client.get("/api/narrative_consent", headers=a.headers))["available"]
            is False
        )
        assert app.state.narrative_gateway is None
        platform = Platform(client, lambda: None)
        _, _, pair = platform.pair(a, b)
        save = platform.save(a, pair)
        updated = platform.accept(a, save, "talk", {"question": "Synthetic question"})
        assert updated["personal"]["dialogue"][0]["answer"] == DEMO_ANSWER
        assert updated["personal"]["dialogue"][0]["mode"] == "demo"
        assert platform.read(b, save)["personal"]["dialogue"] == []
        with client.websocket_connect(
            f"/api/ws/saves/{save['id']}", headers=a.headers
        ) as ws:
            assert ws.receive_json()["save"]["version"] == updated["version"]
        response = client.delete("/api/sessions/current", headers=a.headers)
        assert (
            response.status_code == 204
            and "Max-Age=0" in response.headers["set-cookie"]
        )
        assert client.get("/api/me", headers=a.headers).status_code == 401
        assert client.get("/api/me", headers=b.headers).status_code == 200
    assert len(repositories) == 1
    with pytest.raises(RepositoryError, match="Repository is closed"):
        repositories[0].check_health()


def test_login_keeps_csrf_body_limits_and_rate_limits(connected, publications):
    app = playtest.create_playtest_app(
        connected, test_publication_store=publications[0]
    )
    with TestClient(app, base_url=ORIGIN) as client:
        payload = {"email": "absent@example.invalid", "password": PASSWORD}
        denied = client.post(
            "/api/sessions", json=payload, headers={"Origin": "https://other.invalid"}
        )
        error(denied, 403, "CSRF_REJECTED")
        assert "access-control-allow-origin" not in denied.headers
        error(
            client.post(
                "/api/sessions",
                content=b"x" * (16 * 1024 + 1),
                headers={"Origin": ORIGIN},
            ),
            413,
            "REQUEST_TOO_LARGE",
        )
        for _ in range(5):
            assert (
                client.post(
                    "/api/sessions", json=payload, headers={"Origin": ORIGIN}
                ).status_code
                == 401
            )
        blocked = client.post("/api/sessions", json=payload, headers={"Origin": ORIGIN})
        assert blocked.status_code == 429 and int(blocked.headers["retry-after"]) > 0


def test_launch_cli_with_explicit_approved_publications(connected, deployment_settings):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    env = (
        os.environ
        | connected
        | deployment_settings
        | {
            "TWOWORLDS_HOST": "127.0.0.1",
            "TWOWORLDS_PORT": str(port),
        }
    )
    process = subprocess.Popen(
        [sys.executable, "-m", "twoworlds.playtest"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=1
        ) as client:
            for _ in range(150):
                assert process.poll() is None
                try:
                    assert len(ok(client.get("/api/scripts"))) == 2
                    break
                except httpx.ConnectError:
                    time.sleep(0.1)
            else:
                pytest.fail("Playtest CLI did not start")
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            stdout, stderr = process.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            raise
    assert connected[URI] not in stdout + stderr
    assert connected[SECRET] not in stdout + stderr


def test_launch_cli_cannot_bypass_approval_through_environment(settings, publications):
    env = (
        os.environ
        | settings
        | {
            PUBLICATIONS: str(publications[1]),
            "TWOWORLDS_PLAYTEST_SKIP_DEPLOYMENT_APPROVAL_FOR_TESTS": "1",
        }
    )
    for field in (APPROVAL, PURPOSE):
        env.pop(field, None)
    process = subprocess.run(
        [sys.executable, "-m", "twoworlds.playtest"],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert process.returncode != 0
    assert "Explicit " + APPROVAL in process.stderr
