"""Explicit local/demo storage. Each operation owns its SQLite transaction."""

from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
import sqlite3
from uuid import UUID, uuid4

from pydantic import TypeAdapter, ValidationError

from twoworlds.domain.persistence import (
    AccountRecord,
    CommandReceipt,
    Digest,
    PairRecord,
    SaveRecord,
    UTCDateTime,
)
from twoworlds.ports.repository import (
    CorruptRecord,
    DuplicateRecord,
    InvalidRepositoryTransition,
    MissingRecord,
    ReceiptLimitReached,
    RepositoryError,
)

from .serialization import SerializationError, dumps, loads

_TIME = TypeAdapter(UTCDateTime)
_SCHEMA = """
CREATE TABLE IF NOT EXISTS accounts (
    account_id TEXT PRIMARY KEY NOT NULL,
    recovery_digest TEXT UNIQUE NOT NULL,
    version INTEGER NOT NULL CHECK(version >= 0),
    document TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS account_sessions (
    token_digest TEXT PRIMARY KEY NOT NULL,
    account_id TEXT NOT NULL REFERENCES accounts(account_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS sessions_account ON account_sessions(account_id);
CREATE TABLE IF NOT EXISTS pairs (
    pair_id TEXT PRIMARY KEY NOT NULL,
    invite_digest TEXT UNIQUE NOT NULL,
    member_a TEXT NOT NULL REFERENCES accounts(account_id),
    member_b TEXT REFERENCES accounts(account_id),
    version INTEGER NOT NULL CHECK(version >= 0),
    document TEXT NOT NULL,
    CHECK(member_b IS NULL OR member_b <> member_a)
);
CREATE INDEX IF NOT EXISTS pairs_a ON pairs(member_a);
CREATE INDEX IF NOT EXISTS pairs_b ON pairs(member_b);
CREATE TABLE IF NOT EXISTS saves (
    save_id TEXT PRIMARY KEY NOT NULL,
    pair_id TEXT NOT NULL REFERENCES pairs(pair_id),
    script_id TEXT NOT NULL,
    script_version TEXT NOT NULL,
    version INTEGER NOT NULL CHECK(version BETWEEN 0 AND 512),
    document TEXT NOT NULL,
    UNIQUE(pair_id, script_id)
);
"""
_INDEX_FIELDS = {
    AccountRecord: {
        "account_id": "id",
        "recovery_digest": "recovery_digest",
        "version": "version",
    },
    PairRecord: {
        "pair_id": "id",
        "invite_digest": "invite_digest",
        "member_a": "member_a",
        "member_b": "member_b",
        "version": "version",
    },
    SaveRecord: {
        "save_id": "id",
        "pair_id": "pair_id",
        "script_id": "script_id",
        "script_version": "script_version",
        "version": "version",
    },
}


def _candidate(value, model):
    if not isinstance(value, model):
        raise InvalidRepositoryTransition("Invalid candidate record")
    try:
        return loads(dumps(value), model)
    except (SerializationError, ValidationError, TypeError):
        raise InvalidRepositoryTransition("Invalid candidate record") from None


def _decode(row, model):
    if row is None:
        return None
    try:
        record = loads(row["document"], model)
    except SerializationError:
        raise CorruptRecord("Stored record failed validation") from None
    if any(
        row[column] != getattr(record, field)
        for column, field in _INDEX_FIELDS[model].items()
    ):
        raise CorruptRecord("Stored columns differ from the record")
    return record


def _expected(value: int):
    if type(value) is not int or value < 0:
        raise InvalidRepositoryTransition(
            "Expected version must be a nonnegative integer"
        )


def _now(value: datetime) -> datetime:
    try:
        return _TIME.validate_python(value)
    except (ValueError, TypeError):
        raise InvalidRepositoryTransition("Invalid timestamp") from None


def _transition(current, candidate, immutable_fields):
    if candidate.version != current.version + 1:
        raise InvalidRepositoryTransition("Candidate must advance exactly one version")
    if any(
        getattr(current, field) != getattr(candidate, field)
        for field in immutable_fields
    ):
        raise InvalidRepositoryTransition("Record identity cannot change")
    if candidate.updated_at < current.updated_at:
        raise InvalidRepositoryTransition("Record time cannot move backwards")


class SQLiteRepository:
    """File-backed repository; fresh connections allow independent callers and threads."""

    def __init__(self, path: str | Path):
        self._closed = False
        self._keeper = None
        self._uri = str(path) == ":memory:"
        self._path = (
            f"file:twoworlds_{uuid4().hex}?mode=memory&cache=shared"
            if self._uri
            else str(Path(path).absolute())
        )
        try:
            if self._uri:
                self._keeper = self._connect()
            with self._transaction(write=True) as connection:
                for statement in _SCHEMA.split(";"):
                    if statement.strip():
                        connection.execute(statement)
        except BaseException:
            self.close()
            raise

    def _connect(self):
        connection = sqlite3.connect(
            self._path, uri=self._uri, isolation_level=None, timeout=5
        )
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA busy_timeout=5000")
            return connection
        except BaseException:
            connection.close()
            raise

    @contextmanager
    def _transaction(self, *, write=False):
        if self._closed:
            raise RepositoryError("Repository is closed")
        connection = None
        try:
            connection = self._connect()
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield connection
            connection.commit()
        except sqlite3.IntegrityError as error:
            if connection is not None:
                connection.rollback()
            if error.sqlite_errorcode == sqlite3.SQLITE_CONSTRAINT_FOREIGNKEY:
                raise MissingRecord("Referenced parent is missing") from None
            if error.sqlite_errorcode in {
                sqlite3.SQLITE_CONSTRAINT_UNIQUE,
                sqlite3.SQLITE_CONSTRAINT_PRIMARYKEY,
            }:
                raise DuplicateRecord("A unique record already exists") from None
            raise RepositoryError("Database rejected the transaction") from None
        except sqlite3.Error:
            if connection is not None:
                connection.rollback()
            raise RepositoryError("Database operation failed") from None
        except BaseException:
            if connection is not None:
                connection.rollback()
            raise
        finally:
            if connection is not None:
                connection.close()

    @staticmethod
    def _account(connection, row):
        account = _decode(row, AccountRecord)
        if account is not None:
            indexed = {
                item[0]
                for item in connection.execute(
                    "SELECT token_digest FROM account_sessions WHERE account_id=?",
                    (account.id,),
                )
            }
            if indexed != {session.token_digest for session in account.sessions}:
                raise CorruptRecord("Session index differs from the account")
        return account

    @staticmethod
    def _sessions(connection, account):
        connection.execute(
            "DELETE FROM account_sessions WHERE account_id=?", (account.id,)
        )
        connection.executemany(
            "INSERT INTO account_sessions(token_digest,account_id) VALUES (?,?)",
            [(session.token_digest, account.id) for session in account.sessions],
        )

    def create_account(self, account: AccountRecord) -> AccountRecord:
        account = _candidate(account, AccountRecord)
        with self._transaction(write=True) as connection:
            connection.execute(
                "INSERT INTO accounts(account_id,recovery_digest,version,document) VALUES (?,?,?,?)",
                (account.id, account.recovery_digest, account.version, dumps(account)),
            )
            self._sessions(connection, account)
        return account

    def get_account(self, account_id: str) -> AccountRecord | None:
        with self._transaction() as connection:
            return self._account(
                connection,
                connection.execute(
                    "SELECT * FROM accounts WHERE account_id=?", (account_id,)
                ).fetchone(),
            )

    def get_account_by_recovery_digest(self, digest: Digest) -> AccountRecord | None:
        with self._transaction() as connection:
            return self._account(
                connection,
                connection.execute(
                    "SELECT * FROM accounts WHERE recovery_digest=?", (digest,)
                ).fetchone(),
            )

    def get_account_by_session_digest(
        self, digest: Digest, now: datetime
    ) -> AccountRecord | None:
        now = _now(now)
        with self._transaction() as connection:
            account = self._account(
                connection,
                connection.execute(
                    "SELECT a.* FROM accounts a JOIN account_sessions s ON s.account_id=a.account_id WHERE s.token_digest=?",
                    (digest,),
                ).fetchone(),
            )
            if account and any(
                session.token_digest == digest
                and session.created_at <= now < session.expires_at
                for session in account.sessions
            ):
                return account
            return None

    def compare_and_swap_account(
        self, account_id: str, expected_version: int, candidate: AccountRecord
    ) -> bool:
        _expected(expected_version)
        with self._transaction(write=True) as connection:
            current = self._account(
                connection,
                connection.execute(
                    "SELECT * FROM accounts WHERE account_id=?", (account_id,)
                ).fetchone(),
            )
            if current is None or current.version != expected_version:
                return False
            candidate = _candidate(candidate, AccountRecord)
            _transition(current, candidate, ("id", "recovery_digest", "created_at"))
            changed = connection.execute(
                "UPDATE accounts SET version=?,document=? WHERE account_id=? AND version=?",
                (candidate.version, dumps(candidate), account_id, expected_version),
            ).rowcount
            if not changed:
                return False
            self._sessions(connection, candidate)
            return True

    def create_pair(self, pair: PairRecord) -> PairRecord:
        pair = _candidate(pair, PairRecord)
        if pair.member_b is not None:
            raise InvalidRepositoryTransition("A new pair must have an empty B slot")
        with self._transaction(write=True) as connection:
            connection.execute(
                "INSERT INTO pairs(pair_id,invite_digest,member_a,member_b,version,document) VALUES (?,?,?,?,?,?)",
                (
                    pair.id,
                    pair.invite_digest,
                    pair.member_a,
                    pair.member_b,
                    pair.version,
                    dumps(pair),
                ),
            )
        return pair

    def get_pair(self, pair_id: str) -> PairRecord | None:
        with self._transaction() as connection:
            return _decode(
                connection.execute(
                    "SELECT * FROM pairs WHERE pair_id=?", (pair_id,)
                ).fetchone(),
                PairRecord,
            )

    def list_pairs_for_member(self, member_id: str) -> tuple[PairRecord, ...]:
        with self._transaction() as connection:
            return tuple(
                _decode(row, PairRecord)
                for row in connection.execute(
                    "SELECT * FROM pairs WHERE member_a=? OR member_b=? ORDER BY pair_id",
                    (member_id, member_id),
                )
            )

    def get_pair_by_invite_digest(self, digest: Digest) -> PairRecord | None:
        with self._transaction() as connection:
            return _decode(
                connection.execute(
                    "SELECT * FROM pairs WHERE invite_digest=?", (digest,)
                ).fetchone(),
                PairRecord,
            )

    def join_pair(
        self, pair_id: str, member_id: str, invite_digest: Digest, now: datetime
    ) -> PairRecord | None:
        now = _now(now)
        with self._transaction(write=True) as connection:
            current = _decode(
                connection.execute(
                    "SELECT * FROM pairs WHERE pair_id=?", (pair_id,)
                ).fetchone(),
                PairRecord,
            )
            if (
                current is None
                or current.invite_digest != invite_digest
                or current.member_a == member_id
            ):
                return None
            if current.member_b == member_id:
                return current
            if current.member_b is not None or now >= current.invite_expires_at:
                return None
            if now < current.updated_at:
                raise InvalidRepositoryTransition("Join time precedes pair update")
            candidate = _candidate(
                current.model_copy(
                    update={
                        "member_b": member_id,
                        "version": current.version + 1,
                        "updated_at": now,
                    }
                ),
                PairRecord,
            )
            changed = connection.execute(
                "UPDATE pairs SET member_b=?,version=?,document=? WHERE pair_id=? AND version=? AND member_b IS NULL",
                (
                    member_id,
                    candidate.version,
                    dumps(candidate),
                    pair_id,
                    current.version,
                ),
            ).rowcount
            return candidate if changed else None

    def compare_and_swap_pair(
        self, pair_id: str, expected_version: int, candidate: PairRecord
    ) -> bool:
        _expected(expected_version)
        with self._transaction(write=True) as connection:
            current = _decode(
                connection.execute(
                    "SELECT * FROM pairs WHERE pair_id=?", (pair_id,)
                ).fetchone(),
                PairRecord,
            )
            if current is None or current.version != expected_version:
                return False
            candidate = _candidate(candidate, PairRecord)
            # Only join_pair may claim B after validating an invitation.
            _transition(
                current, candidate, ("id", "member_a", "member_b", "created_at")
            )
            if current.member_b is not None and (
                candidate.invite_digest != current.invite_digest
                or candidate.invite_expires_at != current.invite_expires_at
            ):
                raise InvalidRepositoryTransition(
                    "A filled pair cannot change membership or invite"
                )
            return bool(
                connection.execute(
                    "UPDATE pairs SET invite_digest=?,version=?,document=? WHERE pair_id=? AND version=?",
                    (
                        candidate.invite_digest,
                        candidate.version,
                        dumps(candidate),
                        pair_id,
                        expected_version,
                    ),
                ).rowcount
            )

    def create_save(self, save: SaveRecord) -> SaveRecord:
        save = _candidate(save, SaveRecord)
        with self._transaction(write=True) as connection:
            if (
                connection.execute(
                    "SELECT 1 FROM pairs WHERE pair_id=?", (save.pair_id,)
                ).fetchone()
                is None
            ):
                raise MissingRecord("Parent pair is missing")
            current = _decode(
                connection.execute(
                    "SELECT * FROM saves WHERE pair_id=? AND script_id=?",
                    (save.pair_id, save.script_id),
                ).fetchone(),
                SaveRecord,
            )
            if current is not None:
                return current
            connection.execute(
                "INSERT INTO saves(save_id,pair_id,script_id,script_version,version,document) VALUES (?,?,?,?,?,?)",
                (
                    save.id,
                    save.pair_id,
                    save.script_id,
                    save.script_version,
                    save.version,
                    dumps(save),
                ),
            )
        return save

    def get_save(self, save_id: str) -> SaveRecord | None:
        with self._transaction() as connection:
            return _decode(
                connection.execute(
                    "SELECT * FROM saves WHERE save_id=?", (save_id,)
                ).fetchone(),
                SaveRecord,
            )

    def get_save_for_pair_script(
        self, pair_id: str, script_id: str
    ) -> SaveRecord | None:
        with self._transaction() as connection:
            return _decode(
                connection.execute(
                    "SELECT * FROM saves WHERE pair_id=? AND script_id=?",
                    (pair_id, script_id),
                ).fetchone(),
                SaveRecord,
            )

    def get_receipt(
        self, save_id: str, actor_id: str, request_id: UUID
    ) -> CommandReceipt | None:
        save = self.get_save(save_id)
        if save is None:
            return None
        return next(
            (
                item
                for item in save.receipts
                if item.actor_id == actor_id and item.request_id == request_id
            ),
            None,
        )

    def compare_and_swap_save(
        self, save_id: str, expected_version: int, candidate: SaveRecord
    ) -> bool:
        _expected(expected_version)
        with self._transaction(write=True) as connection:
            current = _decode(
                connection.execute(
                    "SELECT * FROM saves WHERE save_id=?", (save_id,)
                ).fetchone(),
                SaveRecord,
            )
            if current is None or current.version != expected_version:
                return False
            if current.version == 512:
                raise ReceiptLimitReached("Save command capacity reached")
            candidate = _candidate(candidate, SaveRecord)
            _transition(
                current,
                candidate,
                ("id", "pair_id", "script_id", "script_version", "created_at"),
            )
            if (
                len(candidate.receipts) != len(current.receipts) + 1
                or candidate.receipts[:-1] != current.receipts
                or candidate.receipts[-1].accepted_version != candidate.version
            ):
                raise InvalidRepositoryTransition(
                    "Candidate must preserve receipts and append exactly one"
                )
            return bool(
                connection.execute(
                    "UPDATE saves SET version=?,document=? WHERE save_id=? AND version=?",
                    (candidate.version, dumps(candidate), save_id, expected_version),
                ).rowcount
            )

    def close(self) -> None:
        self._closed = True
        if self._keeper is not None:
            self._keeper.close()
            self._keeper = None
