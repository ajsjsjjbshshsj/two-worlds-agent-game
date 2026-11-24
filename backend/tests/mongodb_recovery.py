"""Opt-in recovery suite. Each authenticated MongoDB node is disposable."""

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import time
from uuid import uuid4

from fastapi.testclient import TestClient
from pymongo import MongoClient
from pymongo.errors import OperationFailure, PyMongoError
import pytest

from tests.contracts.support import Identity, Platform, command, ok
from tests.save_support import make_publications
from twoworlds.server import create_server_app

ROOT = Path(__file__).resolve().parents[2]
IMAGE = "mongo:7.0.48"
ADMIN = "drill_operator"
CREDENTIAL = "isolated-fixture-only-auth"
ACCOUNT_PASSWORD = "isolated player password 9"
SOURCE = "twoworlds_drill_source"
ORIGIN = "https://drill.invalid"
QUESTIONS = ("private recovery message A", "private recovery message B")


def run(*args, **kwargs):
    return subprocess.run(
        args, cwd=ROOT, capture_output=True, text=True, timeout=90, **kwargs
    )


def fresh_database():
    return "twoworlds_restore_" + uuid4().hex[:12]


@dataclass
class Node:
    name: str
    port: str
    folder: Path
    admin: MongoClient

    def uri(self, user, db, *, port=None, password=CREDENTIAL):
        return f"mongodb://{user}:{password}@127.0.0.1:{port or self.port}/{db}?directConnection=true&serverSelectionTimeoutMS=2500"

    def provision(self, db, user, role):
        self.admin[db].command("createUser", user, pwd=CREDENTIAL, roles=[role])

    def tools_config(self, db, user, *, password=CREDENTIAL, port="27017"):
        name = "tools-" + uuid4().hex[:12] + ".json"
        path = self.folder / name
        with os.fdopen(
            os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
        ) as file:
            json.dump({"uri": self.uri(user, db, port=port, password=password)}, file)
        return "/run/drill-config/" + name


@contextmanager
def mongo_node(folder, *, authenticated=True):
    folder.mkdir(mode=0o700)
    name = "tw-recovery-" + uuid4().hex[:12]
    credentials = (
        [
            "-e",
            f"MONGO_INITDB_ROOT_USERNAME={ADMIN}",
            "-e",
            f"MONGO_INITDB_ROOT_PASSWORD={CREDENTIAL}",
        ]
        if authenticated
        else []
    )
    run(
        "docker",
        "run",
        "-d",
        "--pull=never",
        "--name",
        name,
        "--publish",
        "127.0.0.1::27017",
        "--tmpfs",
        "/data/db:mode=1777",
        "--ulimit",
        "nofile=8192:8192",
        "--mount",
        f"type=bind,source={folder},target=/run/drill-config,readonly",
        "--log-driver",
        "local",
        "--log-opt",
        "max-size=32k",
        *credentials,
        IMAGE,
        "--wiredTigerCacheSizeGB",
        "0.25",
        check=True,
    )
    try:
        port = (
            run("docker", "port", name, "27017/tcp", check=True)
            .stdout.strip()
            .rsplit(":", 1)[-1]
        )
        userinfo = f"{ADMIN}:{CREDENTIAL}@" if authenticated else ""
        uri = f"mongodb://{userinfo}127.0.0.1:{port}/admin?directConnection=true"
        with MongoClient(uri, serverSelectionTimeoutMS=1200) as admin:
            deadline = time.monotonic() + 50
            while True:
                try:
                    hello = admin.admin.command("hello")
                    assert "setName" not in hello and hello["isWritablePrimary"]
                    assert admin.server_info()["version"] == "7.0.48"
                    break
                except PyMongoError:
                    if time.monotonic() >= deadline:
                        pytest.fail("The dedicated MongoDB node did not become ready.")
                    time.sleep(0.5)
            yield Node(name, port, folder, admin)
    finally:
        run("docker", "rm", "-f", "-v", name, check=True)


@pytest.fixture(scope="module")
def nodes():
    with (
        TemporaryDirectory(prefix="tw-recovery-nodes-") as folder,
        ExitStack() as stack,
    ):
        root = Path(folder)
        source = stack.enter_context(mongo_node(root / "source"))
        target = stack.enter_context(mongo_node(root / "target"))
        yield source, target


@pytest.fixture
def scratch():
    with TemporaryDirectory(prefix="tw-recovery-case-") as folder:
        yield Path(folder)


def operation(script, *args, **settings):
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("MONGO_")
    }
    result = run(
        str(ROOT / "scripts" / f"mongodb-{script}.sh"),
        *map(str, args),
        env=env | settings,
    )
    assert CREDENTIAL not in result.stdout + result.stderr
    return result


class DrillIdentity(Identity):
    @property
    def headers(self):
        return super().headers | {"Origin": ORIGIN}


def application(node, db, store):
    app = create_server_app(
        {
            "TWOWORLDS_MODE": "production",
            "TWOWORLDS_STORAGE_BACKEND": "mongo",
            "TWOWORLDS_ALLOWED_ORIGINS": ORIGIN,
            "TWOWORLDS_COOKIE_SECURE": "1",
            "TWOWORLDS_EMAIL_MODE": "smtp",
            "SMTP_HOST": "mail.example.invalid",
            "SMTP_FROM": "drill@example.invalid",
            "TWOWORLDS_VERIFICATION_SECRET": "local-synthetic-secret-for-recovery",
            "MONGO_URI": node.uri("app", db),
            "MONGO_DATABASE": db,
        },
        publication_store=store,
    )
    return TestClient(app, base_url=ORIGIN)


def login(client, email):
    response = client.post(
        "/api/sessions",
        headers={"Origin": ORIGIN},
        json={"email": email, "password": ACCOUNT_PASSWORD},
    )
    account = ok(response)["account"]
    cookie = response.cookies["tw_session"]
    assert cookie
    return DrillIdentity(account["id"], email, ACCOUNT_PASSWORD, cookie)


def persisted(database):
    return {
        name: (
            list(database[name].find().sort("_id", 1)),
            database[name].index_information(),
        )
        for name in database.list_collection_names()
    }


@pytest.fixture(scope="module")
def store():
    with TemporaryDirectory(prefix="tw-recovery-publication-") as folder:
        publications, publish = make_publications(Path(folder))
        publish()
        yield publications


@pytest.fixture(scope="module")
def seeded(nodes, store):
    src, _ = nodes
    src.provision(SOURCE, "app", "readWrite")
    src.provision(SOURCE, "reader", "read")
    with application(src, SOURCE, store) as client:
        game = Platform(client, lambda: None)
        for name in ("alpha", "bravo"):
            client.app.state.identity_service.register(
                name + "@example.invalid", ACCOUNT_PASSWORD, name
            )
        a, b = [login(client, name + "@example.invalid") for name in ("alpha", "bravo")]
        a, b, pair = game.pair(a, b)
        initial = game.save(a, pair)
        first = command(initial, "inspect", {"target": "maintenance_log"})
        current = ok(game.post(a, initial, first))["save"]
        current = game.accept(b, current, "inspect", {"target": "sea_chart"})
        current = game.accept(a, current, "talk", {"question": QUESTIONS[0]})
        current = game.accept(b, current, "talk", {"question": QUESTIONS[1]})
        assert current["version"] == 4
        before = [game.read(player, current) for player in (a, b)]
    src.admin[SOURCE].create_collection("empty_records")
    data = persisted(src.admin[SOURCE])
    assert (
        len(data["accounts"][0]) == 2
        and len(data["pairs"][0]) == len(data["saves"][0]) == 1
    )
    assert len(data["saves"][0][0]["receipts"]) == 4
    return store, (a, b), pair, initial, first, before, data


def dump(node, folder, db=SOURCE, **overrides):
    settings = {
        "MONGO_CONTAINER": node.name,
        "MONGO_TOOLS_CONFIG": node.tools_config(db, "reader"),
        "MONGO_DATABASE": db,
        "MONGO_BACKUP_DIR": str(folder),
        "MONGO_BACKUP_QUIESCED": "1",
    }
    return operation("backup", **(settings | overrides))


@pytest.fixture(scope="module")
def backup(nodes, seeded):
    with TemporaryDirectory(prefix="tw-recovery-archive-") as folder:
        result = dump(nodes[0], Path(folder))
        assert result.returncode == 0, result.stderr
        yield Path(result.stdout.strip())


def restore(node, bundle, database, **overrides):
    settings = {
        "MONGO_CONTAINER": node.name,
        "MONGO_TOOLS_CONFIG": node.tools_config(database, "restore"),
        "MONGO_RESTORE_DATABASE": database,
    }
    return operation("restore", bundle, **(settings | overrides))


@pytest.fixture
def target(nodes):
    node = nodes[1]
    database = fresh_database()
    node.provision(database, "restore", "readWrite")
    return node, database


def rehash(bundle, name="archive.gz"):
    lines = []
    for filename in ("source-db", name):
        digest = hashlib.sha256((bundle / filename).read_bytes()).hexdigest()
        lines.append(f"{digest}  {filename}\n")
    (bundle / "SHA256SUMS").write_text("".join(lines), encoding="utf-8")


def test_backup_is_private_compressed_and_verified(backup):
    assert backup.name.startswith("backup-") and "Z-" in backup.name
    assert backup.stat().st_mode & 0o777 == 0o700
    assert (backup / "archive.gz").stat().st_mode & 0o777 == 0o600
    assert run("gzip", "-t", backup / "archive.gz").returncode == 0
    assert (
        subprocess.run(
            ["sha256sum", "-c", "SHA256SUMS"], cwd=backup, capture_output=True
        ).returncode
        == 0
    )


def test_empty_database_backup_can_restore_an_empty_collection(nodes, target, scratch):
    source = nodes[0]
    source.admin.drill_empty.create_collection("zero_documents")
    source.provision("drill_empty", "reader", "read")
    result = dump(source, scratch / "empty", db="drill_empty")
    assert result.returncode == 0, result.stderr
    node, db = target
    result = restore(node, Path(result.stdout.strip()), db)
    assert result.returncode == 0, result.stderr
    assert node.admin[db].list_collection_names() == ["zero_documents"]
    assert node.admin[db].zero_documents.count_documents({}) == 0


@pytest.mark.parametrize("damage", ["gzip", "archive", "checksum", "metadata"])
def test_corruption_is_rejected_before_writing(backup, target, scratch, damage):
    node, db = target
    copy = shutil.copytree(backup, scratch / "tampered")
    if damage == "gzip":
        (copy / "archive.gz").write_bytes(b"invalid gzip")
        rehash(copy)
    elif damage == "archive":
        (copy / "archive.gz").write_bytes(
            gzip.compress(b"valid gzip, invalid Mongo archive")
        )
        rehash(copy)
    elif damage == "checksum":
        with (copy / "archive.gz").open("ab") as file:
            file.write(b"unexpected")
    else:
        (copy / "source-db").write_text("another_database\n", encoding="utf-8")
    result = restore(node, copy, db)
    assert result.returncode != 0
    assert {
        "gzip": "gzip verification",
        "archive": "dry-run failed",
        "checksum": "checksum validation",
        "metadata": "checksum validation",
    }[damage] in result.stderr
    assert node.admin[db].list_collection_names() == []


def test_backup_rejects_unwritable_directory(nodes, seeded, scratch):
    denied = scratch / "denied"
    denied.mkdir(mode=0o500)
    try:
        result = dump(nodes[0], denied)
        assert result.returncode != 0 and "writable" in result.stderr
        assert not list(denied.iterdir())
    finally:
        denied.chmod(0o700)


@pytest.mark.parametrize("fault", ["down", "wrong-password"])
def test_dump_failures_are_sanitized_and_leave_no_bundle(nodes, seeded, scratch, fault):
    source = nodes[0]
    overrides = {}
    marker = "wrong-password-recovery-marker"
    if fault == "down":
        # The tools container is healthy, but the isolated endpoint refuses MongoDB.
        overrides["MONGO_TOOLS_CONFIG"] = source.tools_config(
            SOURCE, "reader", port="1"
        )
    else:
        overrides["MONGO_TOOLS_CONFIG"] = source.tools_config(
            SOURCE, "reader", password=marker
        )
    result = dump(source, scratch / "failure", **overrides)
    assert result.returncode != 0 and "Dump failed" in result.stderr
    assert marker not in result.stdout + result.stderr
    assert not list((scratch / "failure").glob("backup-*"))
    assert not list((scratch / "failure").glob(".staging-*"))


def test_recovery_preserves_every_collection_and_application_security(
    seeded, backup, target
):
    store, players, pair, initial, first, before, data = seeded
    node, db = target
    result = restore(node, backup, db)
    assert result.returncode == 0, result.stderr
    assert persisted(node.admin[db]) == data
    node.provision(db, "app", "readWrite")
    with application(node, db, store) as client:
        assert (
            client.get("/health/live").status_code
            == client.get("/health/ready").status_code
            == 200
        )
        game = Platform(client, lambda: None)
        verified = []
        for index, original in enumerate(players):
            # The session preserved by the backup and a fresh login both work.
            assert (
                ok(client.get("/api/me", headers=original.headers))["account"]["id"]
                == original.account_id
            )
            live = login(client, original.email)
            assert (
                live.account_id == original.account_id and live.token != original.token
            )
            relationships = ok(client.get("/api/pairs", headers=live.headers))
            assert [(item["id"], item["role"]) for item in relationships] == [
                (pair["id"], ("a", "b")[index])
            ]
            restored = game.read(live, initial)
            assert restored == before[index] and restored["version"] == 4
            assert restored["personal"]["dialogue"][0]["question"] == QUESTIONS[index]
            assert QUESTIONS[1 - index] not in json.dumps(restored)
            verified.append(live)
        a, b = verified
        assert [clue["id"] for clue in before[0]["personal"]["clues"]] == [
            "a_maintenance_log"
        ]
        assert [clue["id"] for clue in before[1]["personal"]["clues"]] == [
            "b_sea_chart"
        ]
        assert game.receipt(a, initial, first["request_id"])["accepted_version"] == 1
        assert game.receipt(b, initial, first["request_id"]) == {"accepted": False}
        repeated = ok(game.post(a, initial, first))
        assert repeated["receipt"]["duplicate"] and repeated["save"]["version"] == 4
        assert repeated["audio_events"] == []
    print(
        f"Recovered {len(data)} collections, 2 accounts, 1 pair, save v4 and 4 receipts."
    )


def test_restore_without_explicit_separate_target_and_overwrite_are_rejected(
    backup, target
):
    node, db = target
    result = restore(node, backup, db, MONGO_RESTORE_DATABASE="")
    assert result.returncode != 0
    result = restore(node, backup, db, MONGO_DATABASE=db)
    assert result.returncode != 0 and "configured application database" in result.stderr
    known = {"_id": "keep-me", "value": 42}
    node.admin[db].sentinel.insert_one(known)
    baseline = persisted(node.admin[db])
    result = restore(node, backup, db)
    assert result.returncode != 0 and "already contains collections" in result.stderr
    assert persisted(node.admin[db]) == baseline


def identity_at(path):
    run("age-keygen", "-o", path, check=True)
    return run("age-keygen", "-y", path, check=True).stdout.strip()


def test_age_encryption_and_wrong_identity(nodes, seeded, target, scratch):
    identity = scratch / "age-identity"
    recipient = identity_at(identity)
    result = dump(nodes[0], scratch / "encrypted", MONGO_BACKUP_RECIPIENT=recipient)
    assert result.returncode == 0, result.stderr
    bundle = Path(result.stdout.strip())
    assert (
        (bundle / "archive.gz.age").read_bytes().startswith(b"age-encryption.org/v1\n")
    )
    assert {path.name for path in bundle.iterdir()} == {
        "archive.gz.age",
        "SHA256SUMS",
        "source-db",
    }
    wrong = scratch / "wrong"
    identity_at(wrong)
    node, db = target
    result = restore(node, bundle, db, MONGO_RESTORE_IDENTITY_FILE=str(wrong))
    assert result.returncode != 0 and "decryption" in result.stderr
    assert node.admin[db].list_collection_names() == []
    result = restore(node, bundle, db, MONGO_RESTORE_IDENTITY_FILE=str(identity))
    assert result.returncode == 0, result.stderr
    assert persisted(node.admin[db]) == seeded[-1]


def test_retention_waits_for_a_verified_replacement(nodes, seeded, scratch):
    source = nodes[0]
    folder = scratch / "rotation"
    result = dump(source, folder, MONGO_BACKUP_RETENTION_DAYS="1")
    assert result.returncode == 0, result.stderr
    first = Path(result.stdout.strip())
    other_db = "drill_rotation_other"
    source.admin[other_db].create_collection("keep_this_collection")
    source.provision(other_db, "reader", "read")
    result = dump(source, folder, db=other_db, MONGO_BACKUP_RETENTION_DAYS="1")
    assert result.returncode == 0, result.stderr
    other = Path(result.stdout.strip())
    recipient = identity_at(scratch / "rotation-identity")
    result = dump(source, folder, MONGO_BACKUP_RECIPIENT=recipient)
    assert result.returncode == 0, result.stderr
    encrypted = Path(result.stdout.strip())
    unknown = folder / "backup-20200101T000000Z-12345678"
    unknown.mkdir()
    old = time.time() - 3 * 86400
    for bundle in (first, other, encrypted, unknown):
        os.utime(bundle, (old, old))
    result = dump(
        source,
        folder,
        MONGO_BACKUP_RETENTION_DAYS="1",
        MONGO_CONTAINER="unavailable-" + uuid4().hex,
    )
    assert result.returncode != 0 and first.is_dir()
    result = dump(source, folder, MONGO_BACKUP_RETENTION_DAYS="1")
    assert result.returncode == 0, result.stderr
    last = Path(result.stdout.strip())
    assert last.is_dir() and not first.exists()
    assert all(bundle.is_dir() for bundle in (other, encrypted, unknown))


def test_authentication_and_read_only_backup_role_are_enforced(nodes, seeded):
    source = nodes[0]
    with MongoClient(f"mongodb://127.0.0.1:{source.port}/{SOURCE}") as anonymous:
        with pytest.raises(OperationFailure) as error:
            anonymous[SOURCE].accounts.find_one()
        assert error.value.code == 13
    with MongoClient(source.uri("reader", SOURCE)) as reader:
        assert reader[SOURCE].accounts.count_documents({}) == 2
        with pytest.raises(OperationFailure) as error:
            reader[SOURCE].accounts.insert_one({"_id": "must-not-be-inserted"})
        assert error.value.code == 13
