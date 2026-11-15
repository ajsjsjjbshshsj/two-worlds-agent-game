"""Real SQLite constraints and injected SQL failures exercise transaction rollback."""

import sqlite3

import pytest

from twoworlds.ports.repository import CorruptRecord, DuplicateRecord, RepositoryError


@pytest.fixture
def repository_factory(sqlite_repository_factory):
    # SQLite-specific SQL probes stay on SQLite even when shared tests select Mongo.
    return sqlite_repository_factory


def test_sqlite_enforces_unique_and_foreign_keys(tmp_path, world):
    with sqlite3.connect(tmp_path / "repository.sqlite") as db:
        db.execute("PRAGMA foreign_keys=ON")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO account_sessions VALUES (?,?)", ("0" * 64, "missing")
            )
        row = db.execute("SELECT * FROM accounts LIMIT 1").fetchone()
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO accounts VALUES (?,?,?,?)",
                ("duplicate", row[1], row[2], row[3]),
            )
        indexes = db.execute("PRAGMA index_list(saves)").fetchall()
        assert any(index[2] for index in indexes)
        save = db.execute(
            "SELECT pair_id,script_id,script_version,version,document FROM saves"
        ).fetchone()
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO saves VALUES (?,?,?,?,?,?)", ("duplicate_save", *save)
            )


@pytest.mark.parametrize(
    "table,key",
    [("accounts", "account_id"), ("pairs", "pair_id"), ("saves", "save_id")],
)
def test_corrupt_json_is_reported(tmp_path, world, table, key):
    identifier = {"accounts": "account_a", "pairs": "pair_one", "saves": "save_one"}[
        table
    ]
    with sqlite3.connect(tmp_path / "repository.sqlite") as db:
        db.execute(
            f"UPDATE {table} SET document=? WHERE {key}=?", ("not JSON", identifier)
        )
    getter = {
        "accounts": world.get_account,
        "pairs": world.get_pair,
        "saves": world.get_save,
    }[table]
    with pytest.raises(CorruptRecord):
        getter(identifier)


def test_save_list_revalidates_every_document(tmp_path, world):
    with sqlite3.connect(tmp_path / "repository.sqlite") as db:
        db.execute("UPDATE saves SET document='not JSON' WHERE save_id='save_one'")
    with pytest.raises(CorruptRecord):
        world.list_saves_for_pair("pair_one")


def test_account_index_conflict_rolls_back_document_and_index(
    world, account_factory, now
):
    first = world.get_account("account_a")
    other = world.get_account("account_b")
    invalid = first.model_copy(
        update={"version": 1, "sessions": other.sessions, "display_name": "wrong"}
    )
    with pytest.raises(DuplicateRecord):
        world.compare_and_swap_account(first.id, 0, invalid)
    assert world.get_account(first.id) == first
    assert (
        world.get_account_by_session_digest(first.sessions[0].token_digest, now)
        == first
    )
    assert (
        world.get_account_by_session_digest(other.sessions[0].token_digest, now)
        == other
    )


def test_failure_in_session_insert_rolls_back_prior_account_write(tmp_path, world, now):
    first = world.get_account("account_a")
    with sqlite3.connect(tmp_path / "repository.sqlite") as db:
        db.execute("""CREATE TRIGGER stop_sessions BEFORE INSERT ON account_sessions
            BEGIN SELECT RAISE(ABORT,'injected session failure'); END""")
    updated = first.model_copy(update={"version": 1, "display_name": "wrong"})
    with pytest.raises(RepositoryError):
        world.compare_and_swap_account(first.id, 0, updated)
    assert world.get_account(first.id) == first
    assert (
        world.get_account_by_session_digest(first.sessions[0].token_digest, now)
        == first
    )


def test_save_trigger_failure_rolls_back_every_field_and_trigger_side_effect(
    tmp_path, world, save_record, advance
):
    candidate = advance(save_record)
    with sqlite3.connect(tmp_path / "repository.sqlite") as db:
        db.execute("CREATE TABLE audit(message TEXT)")
        db.execute("""CREATE TRIGGER stop_save AFTER UPDATE ON saves BEGIN
            INSERT INTO audit VALUES ('attempted');
            SELECT RAISE(ABORT,'injected save failure');
            END""")
    with pytest.raises(RepositoryError):
        world.compare_and_swap_save(candidate.id, 0, candidate)
    assert world.get_save(candidate.id) == save_record
    assert (
        world.get_receipt(
            candidate.id,
            candidate.receipts[0].actor_id,
            candidate.receipts[0].request_id,
        )
        is None
    )
    with sqlite3.connect(tmp_path / "repository.sqlite") as db:
        assert db.execute("SELECT COUNT(*) FROM audit").fetchone()[0] == 0


def test_closed_repository_rejects_use(repository_factory):
    repo = repository_factory()
    repo.close()
    repo.close()
    with pytest.raises(RepositoryError):
        repo.get_account("missing")


def test_valid_json_with_mismatched_index_columns_is_corrupt(tmp_path, world):
    with sqlite3.connect(tmp_path / "repository.sqlite") as db:
        db.execute("UPDATE saves SET version=1 WHERE save_id='save_one'")
    with pytest.raises(CorruptRecord):
        world.get_save("save_one")


def test_missing_session_index_is_corrupt(tmp_path, world):
    with sqlite3.connect(tmp_path / "repository.sqlite") as db:
        db.execute("DELETE FROM account_sessions WHERE account_id='account_a'")
    with pytest.raises(CorruptRecord):
        world.get_account("account_a")


def test_memory_database_is_shared_across_one_repositorys_operations():
    from twoworlds.storage.sqlite import SQLiteRepository

    repo = SQLiteRepository(":memory:")
    try:
        assert repo.get_save("missing") is None
    finally:
        repo.close()
