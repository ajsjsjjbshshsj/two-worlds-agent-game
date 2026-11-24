"""Exercise the organizer CLI using disposable, authenticated MongoDB."""

from collections import UserDict
import json
import os
from pathlib import Path
import secrets
import socket
import stat
import subprocess
import sys
from tempfile import TemporaryDirectory
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from tests.mongodb_recovery import mongo_node
from twoworlds import playtest, provision_playtest_accounts as cli
from twoworlds.application.identity import IdentityService
from twoworlds.content.publication import PublicationStore
from twoworlds.ports.repository import RepositoryError
from twoworlds.security import mailer
from twoworlds.security.credentials import new_secret

URI = "TWOWORLDS_PLAYTEST_MONGO_URI"
DATABASE = "TWOWORLDS_PLAYTEST_MONGO_DATABASE"
SECRET = "TWOWORLDS_PLAYTEST_VERIFICATION_SECRET"
ORIGIN = "https://playtest.invalid"


def forbidden(*_args, **_kwargs):
    pytest.fail("unexpected access or external integration")


@pytest.fixture(scope="module")
def mongo():
    with TemporaryDirectory(prefix="tw-provision-mongo-") as folder:
        with mongo_node(Path(folder) / "mongo") as node:
            yield node


@pytest.fixture
def settings():
    name = f"twoworlds_playtest_{uuid4().hex}"
    return {
        "TWOWORLDS_MODE": "playtest",
        "TWOWORLDS_AI_MODE": "demo",
        "TWOWORLDS_EMAIL_MODE": "disabled",
        "TWOWORLDS_STORAGE_BACKEND": "mongo",
        "TWOWORLDS_ALLOWED_ORIGINS": ORIGIN,
        DATABASE: name,
        URI: f"mongodb://user:synthetic@127.0.0.1/{name}",
        SECRET: secrets.token_hex(32),
    }


@pytest.fixture
def connected(settings, mongo):
    name = settings[DATABASE]
    mongo.provision(name, "provisioner", "readWrite")
    return settings | {URI: mongo.uri("provisioner", name)}


@pytest.fixture
def paths(tmp_path):
    source = tmp_path / "approved.json"
    source.write_text('["couple-01-a"]', encoding="utf-8")
    output_dir = tmp_path / "private"
    output_dir.mkdir(mode=0o700)
    return source, output_dir / "credentials.jsonl"


def use_environment(monkeypatch, settings):
    for field in (*settings, URI, DATABASE, SECRET):
        if field in settings:
            monkeypatch.setenv(field, settings[field])
        else:
            monkeypatch.delenv(field, raising=False)


def read_records(path):
    return [json.loads(line) for line in path.read_text("utf-8").splitlines()]


def protected_client(app):
    return TestClient(app, base_url=ORIGIN, headers={"Origin": ORIGIN})


def invoke(paths):
    return cli.main([str(path) for path in paths])


def test_empty_git_directory_does_not_mark_ancestors_as_repository(paths, tmp_path):
    (tmp_path / ".git").mkdir()
    with cli._output_directory(paths[1]) as (_, filename):
        assert filename == paths[1].name


@pytest.mark.parametrize(
    "aliases", [["couple-01-a"], ["couple-01-a", "couple-01-b", "couple-02-a"]]
)
def test_create_accounts_without_sessions_then_login(
    connected, mongo, paths, tmp_path, monkeypatch, capsys, aliases
):
    source, output = paths
    source.write_text(json.dumps(aliases), encoding="utf-8")
    use_environment(monkeypatch, connected)
    monkeypatch.setattr(mailer, "build_email_sender", forbidden)
    monkeypatch.setattr(mailer.ConsoleEmailCodeSender, "send_code", forbidden)
    monkeypatch.setattr(mailer.smtplib, "SMTP", forbidden)
    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", forbidden)

    class NoProductionConfig(UserDict):
        def __getitem__(self, key):
            if key in {"MONGO_URI", "MONGO_DATABASE", "TWOWORLDS_VERIFICATION_SECRET"}:
                forbidden()
            return super().__getitem__(key)

    real_open = playtest.open_playtest_repository
    repository = real_open(NoProductionConfig(connected))
    monkeypatch.setattr(cli, "open_playtest_repository", lambda: repository)
    with monkeypatch.context() as provisioning:
        # Account creation must never ask the service to issue a session token.
        provisioning.setattr(IdentityService, "_session", forbidden)
        assert invoke(paths) == 0
    records = read_records(output)
    creds = [row for row in records if row["result"] == "pending"]
    assert [row["alias"] for row in creds] == aliases
    assert len({c["password"] for c in creds}) == len(aliases)
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert output.stat().st_uid == os.geteuid()
    with pytest.raises(RepositoryError, match="Repository is closed"):
        repository.check_health()
    audit = capsys.readouterr()
    assert not audit.err
    entries = [json.loads(line) for line in audit.out.splitlines()]
    assert [entry["result"] for entry in entries] == ["created"] * len(aliases) + [
        "complete"
    ]
    assert [entry["alias"] for entry in entries[:-1]] == aliases
    assert all(
        entry["time"] and entry["batch_id"] == records[0]["batch_id"]
        for entry in entries
    )
    assert all(
        set(entry) <= {"time", "batch_id", "result", "alias"} for entry in entries
    )
    assert all(c["password"] not in audit.out for c in creds)

    db = mongo.admin[connected[DATABASE]]
    assert db.accounts.count_documents({}) == len(aliases)
    assert (
        db.pairs.count_documents({}) == db.verification_codes.count_documents({}) == 0
    )
    for c in creds:
        account = db.accounts.find_one({"email": c["email"]})
        assert account["display_name"] == c["alias"]
        assert account["sessions"] == []
        assert account["password_hash"].startswith("$argon2id$")
        assert c["password"] not in str(account)

    app = playtest.create_playtest_app(
        connected, publication_store=PublicationStore.initialize(tmp_path / "releases")
    )
    with protected_client(app) as client:
        # A token that could have represented an initialization session has no
        # persisted digest and therefore cannot access either protected route.
        unused = new_secret("session")
        cookies = {"Cookie": f"tw_session={unused}"}
        for endpoint in ("/api/me", "/api/pairs"):
            assert client.get(endpoint, headers=cookies).status_code == 401
        for c in creds:
            login = client.post(
                "/api/sessions", json={"email": c["email"], "password": c["password"]}
            )
            assert login.status_code == 200
            session = login.cookies["tw_session"]
            assert session and session != unused
            assert client.get("/api/me").json()["account"]["email"] == c["email"]
            assert db.accounts.find_one({"email": c["email"]})["sessions"]
            assert client.delete("/api/sessions/current").status_code == 204
            assert (
                client.get(
                    "/api/me", headers={"Cookie": f"tw_session={session}"}
                ).status_code
                == 401
            )


@pytest.mark.parametrize(
    "raw",
    [
        b'["couple-01-a","couple-01-a"]',
        b'["couple-01-a","approval-private@example.com"]',
        b'["couple-01-a","Couple-01-b"]',
        b'["couple-01-a",123]',
        b'["couple-01-a",{}]',
        b'{"aliases":["couple-01-a"]}',
        b"[]",
        b'["couple-01-a"',
        b"\xff",
        b" " * (16 * 1024 + 1),
    ],
)
def test_full_alias_validation_precedes_repository_and_output(
    raw, paths, monkeypatch, capsys
):
    source, output = paths
    source.write_bytes(raw)
    monkeypatch.setattr(cli, "open_playtest_repository", forbidden)
    assert invoke(paths) == 1
    assert not output.exists()
    assert "approval-private" not in capsys.readouterr().err


def test_existing_alias_rejects_whole_batch_without_overwrite(
    connected, mongo, paths, monkeypatch
):
    use_environment(monkeypatch, connected)
    db = mongo.admin[connected[DATABASE]]
    assert invoke(paths) == 0
    old_account = db.accounts.find_one()
    old_journal = paths[1].read_bytes()
    source, output = paths[0], paths[1].with_name("another-batch.jsonl")
    source.write_text('["new-alias","couple-01-a"]', encoding="utf-8")
    assert invoke((source, output)) == 1
    assert not output.exists()
    assert list(db.accounts.find()) == [old_account]
    assert paths[1].read_bytes() == old_journal


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"TWOWORLDS_MODE": "production"}, "MODE=playtest"),
        ({"TWOWORLDS_MODE": "demo"}, "MODE=playtest"),
        ({"TWOWORLDS_EMAIL_MODE": "smtp"}, "EMAIL_MODE=disabled"),
        ({"TWOWORLDS_AI_MODE": "provider"}, "AI_MODE=demo"),
        ({DATABASE: "twoworlds"}, "dedicated twoworlds_playtest_"),
    ],
)
def test_refuses_nonplaytest_and_production_configuration(
    settings, paths, monkeypatch, capsys, change, message
):
    use_environment(monkeypatch, settings | change)
    monkeypatch.setattr(playtest, "MongoRepository", forbidden)
    assert invoke(paths) == 1
    assert message in capsys.readouterr().err
    assert not paths[1].exists()


def test_no_production_fallback(settings, paths, monkeypatch, capsys):
    del settings[URI]
    use_environment(monkeypatch, settings)
    monkeypatch.setenv(
        "MONGO_URI", "mongodb://formal-user:production-marker@localhost/twoworlds"
    )
    monkeypatch.setenv("MONGO_DATABASE", "twoworlds")
    monkeypatch.setattr(playtest, "MongoRepository", forbidden)
    assert invoke(paths) == 1
    err = capsys.readouterr().err
    assert URI in err and "production-marker" not in err
    assert not paths[1].exists()


def test_unavailable_database_creates_no_credentials_or_accounts(
    settings, paths, monkeypatch, capsys
):
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        settings[URI] = (
            f"mongodb://user:private-connection-marker@127.0.0.1:{reserved.getsockname()[1]}/{settings[DATABASE]}"
        )
        use_environment(monkeypatch, settings)
        assert invoke(paths) == 1
    reports = capsys.readouterr()
    assert "private-connection-marker" not in reports.err + reports.out
    assert not paths[1].exists()


def test_reuses_authentication_probe_on_real_noauth_server(
    settings, paths, monkeypatch
):
    with TemporaryDirectory(prefix="tw-provision-noauth-") as folder:
        with mongo_node(Path(folder) / "mongo", authenticated=False) as node:
            name = settings[DATABASE]
            node.provision(name, "provisioner", "readWrite")
            use_environment(
                monkeypatch, settings | {URI: node.uri("provisioner", name)}
            )
            assert invoke(paths) == 1
            assert node.admin[name].list_collection_names() == []
    assert not paths[1].exists()


@pytest.mark.parametrize(
    "case",
    [
        "exists",
        "symlink",
        "broken-link",
        "linked-parent",
        "open-parent",
        "git-tree",
        "git-metadata",
        "git-dir",
    ],
)
def test_output_safety_rejects_before_any_account_write(
    case, paths, tmp_path, monkeypatch
):
    source, output = paths
    sentinel = tmp_path / "untouched"
    sentinel.write_bytes(b"sentinel")
    if case == "exists":
        output.write_bytes(b"existing")
    if case == "symlink":
        output.symlink_to(sentinel)
    if case == "broken-link":
        output.symlink_to(tmp_path / "not-created")
    if case == "linked-parent":
        parent = tmp_path / "linked"
        parent.symlink_to(output.parent, target_is_directory=True)
        output = parent / output.name
    if case == "open-parent":
        output.parent.chmod(0o750)
    if case == "git-tree":
        (tmp_path / ".git").write_text("gitdir: worktree-metadata")
    if case == "git-metadata":
        git = tmp_path / ".git"
        git.mkdir()
        (git / "HEAD").write_text("ref: refs/heads/main")
    if case == "git-dir":
        (tmp_path / "HEAD").write_text("ref: refs/heads/main")
        (tmp_path / "refs").mkdir()
        (tmp_path / "objects").mkdir()
    monkeypatch.setattr(cli, "open_playtest_repository", forbidden)
    assert invoke((source, output)) == 1
    assert sentinel.read_bytes() == b"sentinel"
    if case == "exists":
        assert output.read_bytes() == b"existing"
    else:
        assert not (tmp_path / "private" / output.name).exists() or output.is_symlink()
        assert not (tmp_path / "not-created").exists()


def test_exclusive_open_rechecks_after_preflight(connected, paths, mongo, monkeypatch):
    source, output = paths

    def concurrent_file():
        output.write_bytes(b"another process owns this file")
        return playtest.open_playtest_repository(connected)

    monkeypatch.setattr(cli, "open_playtest_repository", concurrent_file)
    assert invoke((source, output)) == 1
    assert output.read_bytes() == b"another process owns this file"
    assert mongo.admin[connected[DATABASE]].accounts.count_documents({}) == 0


@pytest.mark.parametrize("committed", [False, True])
def test_partial_batch_retains_journal_on_uncertain_insert(
    connected, mongo, paths, monkeypatch, capsys, committed
):
    use_environment(monkeypatch, connected)
    source, output = paths
    source.write_text(
        '["first-account","second-account","third-account"]', encoding="utf-8"
    )
    real_create = playtest.MongoRepository.create_account

    def interrupted(repository, account):
        if account.display_name == "second-account":
            if committed:
                real_create(repository, account)
            raise RepositoryError("storage implementation secret marker")
        return real_create(repository, account)

    monkeypatch.setattr(playtest.MongoRepository, "create_account", interrupted)
    assert invoke(paths) == 1
    actual = list(mongo.admin[connected[DATABASE]].accounts.find().sort("email", 1))
    assert [record["display_name"] for record in actual] == (
        ["first-account", "second-account"] if committed else ["first-account"]
    )
    assert all(record["sessions"] == [] for record in actual)
    records = read_records(output)
    assert [(row["alias"], row["result"]) for row in records] == [
        ("first-account", "pending"),
        ("first-account", "created"),
        ("second-account", "pending"),
        ("second-account", "unknown"),
    ]
    reports = capsys.readouterr()
    audit = reports.out + reports.err
    assert "storage implementation secret marker" not in audit
    assert all(
        rec.get("password", "unused-password-marker") not in audit for rec in records
    )
    assert stat.S_IMODE(output.stat().st_mode) == 0o600

    # A retry with a fresh file detects the existing first account and does
    # not rotate its password or create any other account.
    retry = output.with_name("retry.jsonl")
    assert invoke((source, retry)) == 1 and not retry.exists()
    assert (
        list(mongo.admin[connected[DATABASE]].accounts.find().sort("email", 1))
        == actual
    )


def test_module_entrypoint_cli(connected, paths):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "twoworlds.provision_playtest_accounts",
            *map(str, paths),
        ],
        env=os.environ | connected,
        text=True,
        capture_output=True,
        timeout=20,
    )
    assert result.returncode == 0 and not result.stderr
    records = read_records(paths[1])
    assert records[-1]["result"] == "complete"
    assert records[0]["password"] not in result.stdout
    assert connected[URI] not in result.stdout


def test_parser_never_echoes_credential_arguments(capsys):
    with pytest.raises(SystemExit) as caught:
        cli.main(["a.json", "b.json", "--unknown", "private-argument-marker"])
    assert caught.value.code == 2
    assert "private-argument-marker" not in capsys.readouterr().err
