"""Database-independent identity workflows. HTTP policy belongs to T06.2."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import wraps
import secrets
from typing import Callable

from pydantic import TypeAdapter, ValidationError

from twoworlds.domain.persistence import (
    AccountRecord,
    DisplayName,
    SessionRecord,
    UTCDateTime,
)
from twoworlds.ports.repository import DuplicateRecord, Repository, RepositoryError
from twoworlds.security.credentials import digest_secret, new_secret


class IdentityError(RuntimeError):
    """Safe codes without caller inputs or storage error text."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(
            {
                "UNAUTHENTICATED": "身份凭证无效。",
                "INVALID_INPUT": "身份输入无效。",
                "CONCURRENT_UPDATE": "身份更新竞争，请重试。",
                "DEPENDENCY_UNAVAILABLE": "身份存储暂不可用。",
                "GENERATION_FAILED": "无法生成新的身份凭证。",
                "CLOCK_ERROR": "身份服务时间无效。",
            }[code]
        )


@dataclass(frozen=True)
class AccountInfo:
    id: str
    display_name: str


@dataclass(frozen=True)
class SessionIssued:
    account: AccountInfo
    expires_at: datetime
    token: str = field(repr=False)


@dataclass(frozen=True)
class AccountCreated(SessionIssued):
    recovery_key: str = field(repr=False)


def _storage_errors(method):
    @wraps(method)
    def wrapped(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except RepositoryError:
            raise IdentityError("DEPENDENCY_UNAVAILABLE") from None

    return wrapped


class IdentityService:
    def __init__(
        self,
        repository: Repository,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        credential_generator: Callable[[], str] | None = None,
        max_attempts: int = 8,
    ):
        if type(max_attempts) is not int or not 1 <= max_attempts <= 32:
            raise ValueError("max_attempts must be between 1 and 32")
        self._repository = repository
        self._clock = clock
        self._generator = credential_generator
        self._attempts = max_attempts

    def _now(self):
        try:
            return TypeAdapter(UTCDateTime).validate_python(self._clock())
        except Exception:
            raise IdentityError("CLOCK_ERROR") from None

    def _secret(self, kind):
        try:
            return new_secret(kind, self._generator)
        except Exception:
            raise IdentityError("GENERATION_FAILED") from None

    @staticmethod
    def _digest(value, kind):
        try:
            return digest_secret(value, kind)
        except ValueError:
            raise IdentityError("UNAUTHENTICATED") from None

    @staticmethod
    def _info(account):
        return AccountInfo(account.id, account.display_name)

    @_storage_errors
    def create_account(self, display_name: str) -> AccountCreated:
        try:
            name = TypeAdapter(DisplayName).validate_python(display_name)
        except ValidationError:
            raise IdentityError("INVALID_INPUT") from None
        for _ in range(self._attempts):
            recovery, token = self._secret("recovery"), self._secret("session")
            now = self._now()
            session = SessionRecord(
                token_digest=digest_secret(token),
                created_at=now,
                expires_at=now + timedelta(days=7),
            )
            account = AccountRecord(
                id="account_" + secrets.token_hex(16),
                display_name=name,
                recovery_digest=digest_secret(recovery),
                sessions=(session,),
                created_at=now,
                updated_at=now,
            )
            try:
                saved = self._repository.create_account(account)
            except DuplicateRecord:
                continue
            return AccountCreated(
                self._info(saved), session.expires_at, token, recovery
            )
        raise IdentityError("GENERATION_FAILED")

    @_storage_errors
    def recover(self, recovery_key: str) -> SessionIssued:
        digest = self._digest(recovery_key, "recovery")
        for _ in range(self._attempts):
            current = self._repository.get_account_by_recovery_digest(digest)
            if current is None:
                raise IdentityError("UNAUTHENTICATED")
            now = self._now()
            if now < current.updated_at or any(
                s.created_at > now for s in current.sessions
            ):
                raise IdentityError("CLOCK_ERROR")
            token = self._secret("session")
            token_digest = digest_secret(token)
            if any(s.token_digest == token_digest for s in current.sessions):
                continue
            session = SessionRecord(
                token_digest=token_digest,
                created_at=now,
                expires_at=now + timedelta(days=7),
            )
            retained = [s for s in current.sessions if s.expires_at > now]
            # Stable sort preserves acceptance order for equal clock timestamps;
            # the new session wins a tie without deleting an arbitrary device.
            retained.append(session)
            retained.sort(key=lambda s: s.created_at)
            candidate = AccountRecord.model_validate(
                current.model_dump()
                | {
                    "sessions": tuple(retained[-5:]),
                    "version": current.version + 1,
                    "updated_at": now,
                }
            )
            try:
                accepted = self._repository.compare_and_swap_account(
                    current.id, current.version, candidate
                )
            except DuplicateRecord:
                continue
            if accepted:
                return SessionIssued(self._info(candidate), session.expires_at, token)
        raise IdentityError("CONCURRENT_UPDATE")

    @_storage_errors
    def authenticate(self, token: str) -> AccountRecord:
        digest = self._digest(token, "session")
        now = self._now()
        return self._authenticated(digest, now)

    def _authenticated(self, digest, now):
        current = self._repository.get_account_by_session_digest(digest, now)
        if current is None or not any(
            s.token_digest == digest and s.created_at <= now < s.expires_at
            for s in current.sessions
        ):
            raise IdentityError("UNAUTHENTICATED")
        return current

    @_storage_errors
    def revoke(self, token: str) -> None:
        digest = self._digest(token, "session")
        for _ in range(self._attempts):
            now = self._now()
            current = self._authenticated(digest, now)
            if now < current.updated_at:
                raise IdentityError("CLOCK_ERROR")
            candidate = AccountRecord.model_validate(
                current.model_dump()
                | {
                    "sessions": tuple(
                        s for s in current.sessions if s.token_digest != digest
                    ),
                    "version": current.version + 1,
                    "updated_at": now,
                }
            )
            if self._repository.compare_and_swap_account(
                current.id, current.version, candidate
            ):
                return
        raise IdentityError("CONCURRENT_UPDATE")
