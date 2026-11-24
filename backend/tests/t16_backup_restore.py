"""T16.2 local backup/restore drill with the official MongoDB Database Tools.

The production bash wrappers (scripts/mongodb-*.sh) need Linux-only flock/stat
and are exercised by CI on ubuntu; on Windows this module performs the same
substantive drill through `docker exec mongodump/mongorestore`:

seed an isolated source database through the real services, dump a compressed
archive, verify its checksum, restore into a SEPARATE new database, compare
every collection document-for-document, prove the source is untouched, and
re-check role projection isolation on the restored data.

Opt-in: requires MONGO_URI and a reachable Docker container named by
MONGO_CONTAINER (default twoworlds-mongo). Never touches a production database.
"""

import gzip
import hashlib
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pymongo import MongoClient

from twoworlds.application.pairs import PairService
from twoworlds.application.saves import SaveService
from twoworlds.domain.persistence import AccountRecord, SessionRecord
from twoworlds.storage.mongo import MongoRepository

pytestmark = pytest.mark.skipif(
    not os.environ.get("MONGO_URI"), reason="T16.2 drill needs a real MongoDB"
)
CONTAINER = os.environ.get("MONGO_CONTAINER", "twoworlds-mongo")
NOW = datetime(2026, 11, 23, 12, 0, tzinfo=timezone.utc)


def docker(*args, stdin=None):
    return subprocess.run(
        ["docker", *args], input=stdin, capture_output=True, timeout=120, check=True
    )


def account(identifier):
    return AccountRecord(
        id="account_" + identifier,
        email=f"t16-{identifier}@example.com",
        email_verified_at=NOW,
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$" + "1" * 40,
        display_name="验收" + identifier,
        sessions=(
            SessionRecord(
                token_digest=identifier * 64,
                created_at=NOW,
                expires_at=NOW + timedelta(days=1),
            ),
        ),
        created_at=NOW,
        updated_at=NOW,
    )


def test_backup_restore_preserves_data_and_isolation(tmp_path):
    from tests.save_support import make_publications

    source = "t16_src_" + uuid4().hex[:10]
    target = "t16_dst_" + uuid4().hex[:10]
    uri = os.environ["MONGO_URI"]
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    repo = MongoRepository(uri, source)
    try:
        repo.create_account(account("a"))
        repo.create_account(account("b"))
        pairs = PairService(repo)
        pair = pairs.create_pair("account_a")
        pairs.join_pair("account_b", pair.invite_token)
        store, publish = make_publications(tmp_path / "releases")
        publish()
        saves = SaveService(repo, store)
        snapshot = saves.create_save("account_a", pair.id, "lighthouse", "1.0.0")
        from twoworlds.application.commands import GameCommand

        result = saves.submit_command(
            "account_a",
            snapshot.id,
            GameCommand(
                request_id=uuid4(),
                expected_version=0,
                kind="inspect",
                args={"target": "maintenance_log"},
            ),
        )
        assert result.receipt.accepted_version == 1
        before = {
            name: list(client[source][name].find().sort("_id"))
            for name in client[source].list_collection_names()
        }
        assert {"accounts", "pairs", "saves"} <= set(before)

        bundle = tmp_path / "bundle"
        bundle.mkdir(mode=0o700)
        archive = bundle / "archive.gz"
        dump = docker(
            "exec",
            CONTAINER,
            "mongodump",
            "--quiet",
            "--host",
            "127.0.0.1",
            "--db",
            source,
            "--archive",
            "--gzip",
        ).stdout
        archive.write_bytes(dump)
        assert source.encode() in gzip.decompress(dump)
        (bundle / "source-db").write_text(source + "\n", encoding="utf-8")
        digest = hashlib.sha256(dump).hexdigest()
        (bundle / "SHA256SUMS").write_text(f"{digest}  archive.gz\n", encoding="utf-8")
        # Checksum verification must pass before any restore is attempted.
        assert hashlib.sha256(archive.read_bytes()).hexdigest() == digest

        assert target != source
        docker(
            "exec",
            "-i",
            CONTAINER,
            "mongorestore",
            "--quiet",
            "--host",
            "127.0.0.1",
            "--archive",
            "--gzip",
            "--nsFrom",
            f"{source}.*",
            "--nsTo",
            f"{target}.*",
            stdin=dump,
        )
        after_source = {
            name: list(client[source][name].find().sort("_id"))
            for name in client[source].list_collection_names()
        }
        assert after_source == before, "restore must not modify the source database"
        for name, documents in before.items():
            restored = list(client[target][name].find().sort("_id"))
            assert restored == documents, f"collection {name} differs after restore"

        # Application-level isolation still holds on the restored database.
        restored_repo = MongoRepository(uri, target)
        try:
            restored_saves = SaveService(restored_repo, store)
            own = restored_saves.read_save("account_a", snapshot.id)
            other = restored_saves.read_save("account_b", snapshot.id)
            own_clues = {c.id for c in own.personal.clues}
            other_clues = {c.id for c in other.personal.clues}
            assert "a_maintenance_log" in own_clues
            assert "a_maintenance_log" not in other_clues
            assert own.personal.clues[0].text not in json.dumps(
                other.model_dump(mode="json"), ensure_ascii=False
            )
        finally:
            restored_repo.close()
    finally:
        repo.close()
        client.drop_database(source)
        client.drop_database(target)
        client.close()
