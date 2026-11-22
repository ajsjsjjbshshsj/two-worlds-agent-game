"""Database-independent email account workflows. HTTP policy lives in the API."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import wraps
import secrets
from typing import Callable

from pydantic import TypeAdapter, ValidationError

from twoworlds.domain.persistence import (
    AccountRecord,
    DisplayName,
    Email,
    SessionRecord,
    UTCDateTime,
)
from twoworlds.ports.repository import DuplicateRecord, Repository, RepositoryError
from twoworlds.security.credentials import digest_secret, new_secret
from twoworlds.security.passwords import (
    Password,
    dummy_verify,
    hash_password,
    needs_rehash,
    verify_password,
)

_EMAIL = TypeAdapter(Email)
_PASSWORD = TypeAdapter(Password)
_NAME = TypeAdapter(DisplayName)
_TIME = TypeAdapter(UTCDateTime)


class IdentityError(RuntimeError):
    """Safe codes without caller inputs or storage error text."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(
            {
                "UNAUTHENTICATED": "身份凭证无效。",
                "INVALID_CREDENTIALS": "邮箱或密码错误。",
                "INVALID_INPUT": "身份输入无效。",
                "EMAIL_ALREADY_REGISTERED": "该邮箱已注册。",
                "CONCURRENT_UPDATE": "身份更新竞争，请重试。",
                "DEPENDENCY_UNAVAILABLE": "身份存储暂不可用。",
                "GENERATION_FAILED": "无法生成新的身份凭证。",
                "CLOCK_ERROR": "身份服务时间无效。",
            }[code]
        )


@dataclass(frozen=True)
class AccountInfo:
    id: str
    email: str
    display_name: str


@dataclass(frozen=True)
class SessionIssued:
    account: AccountInfo
    expires_at: datetime
    token: str = field(repr=False)


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
            return _TIME.validate_python(self._clock())
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
        return AccountInfo(account.id, account.email, account.display_name)

    @staticmethod
    def _email(value):
        try:
            return _EMAIL.validate_python(value)
        except ValidationError:
            raise IdentityError("INVALID_INPUT") from None

    @staticmethod
    def _password(value):
        try:
            return _PASSWORD.validate_python(value)
        except ValidationError:
            raise IdentityError("INVALID_INPUT") from None

    @staticmethod
    def _hash(password):
        try:
            return hash_password(password)
        except Exception:
            raise IdentityError("GENERATION_FAILED") from None

    def _session(self, now):
        token = self._secret("session")
        return token, SessionRecord(
            token_digest=digest_secret(token),
            created_at=now,
            expires_at=now + timedelta(days=7),
        )

    @_storage_errors
    def register(self, email: str, password: str, display_name: str) -> SessionIssued:
        """The caller must already have consumed a valid register code."""
        email = self._email(email)
        password = self._password(password)
        try:
            name = _NAME.validate_python(display_name)
        except ValidationError:
            raise IdentityError("INVALID_INPUT") from None
        password_hash = self._hash(password)
        for _ in range(self._attempts):
            if self._repository.get_account_by_email(email) is not None:
                raise IdentityError("EMAIL_ALREADY_REGISTERED")
            now = self._now()
            token, session = self._session(now)
            account = AccountRecord(
                id="account_" + secrets.token_hex(16),
                email=email,
                email_verified_at=now,
                password_hash=password_hash,
                display_name=name,
                sessions=(session,),
                created_at=now,
                updated_at=now,
            )
            try:
                saved = self._repository.create_account(account)
            except DuplicateRecord:
                # The unique email constraint means a concurrent register won.
                raise IdentityError("EMAIL_ALREADY_REGISTERED") from None
            return SessionIssued(self._info(saved), session.expires_at, token)
        raise IdentityError("CONCURRENT_UPDATE")

    @_storage_errors
    def login(self, email: str, password: str) -> SessionIssued:
        email = self._email(email)
        if type(password) is not str or not 10 <= len(password) <= 128:
            dummy_verify(password if type(password) is str else "")
            raise IdentityError("INVALID_CREDENTIALS")
        current = self._repository.get_account_by_email(email)
        if current is None:
            dummy_verify(password)
            raise IdentityError("INVALID_CREDENTIALS")
        if not verify_password(current.password_hash, password):
            raise IdentityError("INVALID_CREDENTIALS")
        upgraded = self._hash(password) if needs_rehash(current.password_hash) else None
        for _ in range(self._attempts):
            current = self._repository.get_account_by_email(email)
            if current is None or not verify_password(current.password_hash, password):
                raise IdentityError("INVALID_CREDENTIALS")
            now = self._now()
            if now < current.updated_at or any(
                s.created_at > now for s in current.sessions
            ):
                raise IdentityError("CLOCK_ERROR")
            token, session = self._session(now)
            if any(s.token_digest == session.token_digest for s in current.sessions):
                continue
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
                | ({"password_hash": upgraded} if upgraded else {})
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
    def reset_password(self, email: str, new_password: str) -> None:
        """The caller must already have consumed a valid reset code."""
        email = self._email(email)
        new_password = self._password(new_password)
        password_hash = self._hash(new_password)
        for _ in range(self._attempts):
            current = self._repository.get_account_by_email(email)
            if current is None:
                raise IdentityError("INVALID_INPUT")
            now = self._now()
            if now < current.updated_at:
                raise IdentityError("CLOCK_ERROR")
            candidate = AccountRecord.model_validate(
                current.model_dump()
                | {
                    "password_hash": password_hash,
                    "sessions": (),
                    "version": current.version + 1,
                    "updated_at": now,
                }
            )
            if self._repository.compare_and_swap_account(
                current.id, current.version, candidate
            ):
                return
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
        if now < current.updated_at:
            raise IdentityError("CLOCK_ERROR")
        return current

    @_storage_errors
    def set_narrative_consent(
        self, token: str, disclosure: str | None
    ) -> AccountRecord:
        digest = self._digest(token, "session")
        for _ in range(self._attempts):
            now = self._now()
            current = self._authenticated(digest, now)
            if current.narrative_consent == disclosure:
                return current
            candidate = AccountRecord.model_validate(
                current.model_dump()
                | {
                    "narrative_consent": disclosure,
                    "version": current.version + 1,
                    "updated_at": now,
                }
            )
            if self._repository.compare_and_swap_account(
                current.id, current.version, candidate
            ):
                return candidate
        raise IdentityError("CONCURRENT_UPDATE")

    @_storage_errors
    def revoke(self, token: str) -> None:
        digest = self._digest(token, "session")
        for _ in range(self._attempts):
            now = self._now()
            current = self._authenticated(digest, now)
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
