"""Single-use email verification codes with atomic attempt/consume transitions."""

from datetime import datetime, timedelta, timezone
from functools import wraps
from hashlib import sha256
import logging
import secrets
from typing import Callable, Literal

from pydantic import TypeAdapter, ValidationError

from twoworlds.domain.persistence import Email, UTCDateTime, VerificationCodeRecord
from twoworlds.ports.email import EmailCodeSender
from twoworlds.ports.repository import DuplicateRecord, Repository, RepositoryError
from twoworlds.security.credentials import digests_equal, verification_digest

_EMAIL = TypeAdapter(Email)
_TIME = TypeAdapter(UTCDateTime)
_PURPOSES = ("register", "reset")
_logger = logging.getLogger("twoworlds.email")


class VerificationError(RuntimeError):
    """Safe codes; messages never contain emails, codes, or storage text."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(
            {
                "INVALID_INPUT": "验证码输入无效。",
                "INVALID_CODE": "验证码无效。",
                "CODE_EXPIRED": "验证码已过期，请重新申请。",
                "CODE_LOCKED": "验证码尝试次数已用尽，请重新申请。",
                "SEND_FAILED": "验证码邮件发送失败。",
                "CONCURRENT_UPDATE": "验证码更新竞争，请重试。",
                "DEPENDENCY_UNAVAILABLE": "验证码服务暂不可用。",
                "CLOCK_ERROR": "验证码服务时间无效。",
            }[code]
        )


def _storage_errors(method):
    @wraps(method)
    def wrapped(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except RepositoryError:
            raise VerificationError("DEPENDENCY_UNAVAILABLE") from None

    return wrapped


def code_id(email: str, purpose: str) -> str:
    # One live code per (email, purpose); the id is a non-secret lookup key.
    return (
        "code_" + sha256(f"tw-code:{email}:{purpose}".encode("utf-8")).hexdigest()[:59]
    )


class VerificationCodeService:
    def __init__(
        self,
        repository: Repository,
        sender: EmailCodeSender,
        *,
        secret: str,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        code_generator: Callable[[], str] | None = None,
        max_attempts: int = 8,
        ttl: timedelta = timedelta(minutes=10),
        max_verify_attempts: int = 5,
    ):
        if type(secret) is not str or len(secret) < 32:
            raise ValueError("Verification secret must be a string of 32+ characters")
        if type(max_attempts) is not int or not 1 <= max_attempts <= 32:
            raise ValueError("max_attempts must be between 1 and 32")
        if ttl <= timedelta(0):
            raise ValueError("Code TTL must be positive")
        if type(max_verify_attempts) is not int or not 1 <= max_verify_attempts <= 5:
            raise ValueError("max_verify_attempts must be between 1 and 5")
        self._repository = repository
        self._sender = sender
        self._secret = secret
        self._clock = clock
        self._generator = code_generator
        self._attempts = max_attempts
        self._ttl = ttl
        self._max_verify = max_verify_attempts

    def _now(self):
        try:
            return _TIME.validate_python(self._clock())
        except Exception:
            raise VerificationError("CLOCK_ERROR") from None

    def _code(self) -> str:
        try:
            value = (
                f"{secrets.randbelow(1_000_000):06d}"
                if self._generator is None
                else self._generator()
            )
        except Exception:
            raise VerificationError("DEPENDENCY_UNAVAILABLE") from None
        if (
            type(value) is not str
            or len(value) != 6
            or not value.isascii()
            or not value.isdigit()
        ):
            raise VerificationError("DEPENDENCY_UNAVAILABLE")
        return value

    @staticmethod
    def _validated(email, purpose):
        if purpose not in _PURPOSES:
            raise VerificationError("INVALID_INPUT")
        try:
            return _EMAIL.validate_python(email)
        except ValidationError:
            raise VerificationError("INVALID_INPUT") from None

    def _candidate(self, current, now, **changes):
        return VerificationCodeRecord.model_validate(
            current.model_dump()
            | changes
            | {"version": current.version + 1, "updated_at": now}
        )

    @_storage_errors
    def request_code(self, email: str, purpose: Literal["register", "reset"]) -> None:
        email = self._validated(email, purpose)
        now = self._now()
        self._repository.delete_expired_verification_codes(now)
        if purpose == "reset" and self._repository.get_account_by_email(email) is None:
            # Unknown emails get the same external 202 but no stored code.
            return
        code = self._code()
        digest = verification_digest(self._secret, email, purpose, code)
        identifier = code_id(email, purpose)
        stored = False
        for _ in range(self._attempts):
            now = self._now()
            current = self._repository.get_verification_code(identifier)
            try:
                if current is None:
                    self._repository.create_verification_code(
                        VerificationCodeRecord(
                            id=identifier,
                            email=email,
                            purpose=purpose,
                            digest=digest,
                            created_at=now,
                            expires_at=now + self._ttl,
                            attempts=0,
                            consumed_at=None,
                            version=0,
                            updated_at=now,
                        )
                    )
                else:
                    if now < current.updated_at:
                        raise VerificationError("CLOCK_ERROR")
                    # Resend replaces the old digest, so the previous code dies.
                    accepted = self._repository.compare_and_swap_verification_code(
                        identifier,
                        current.version,
                        self._candidate(
                            current,
                            now,
                            digest=digest,
                            created_at=now,
                            expires_at=now + self._ttl,
                            attempts=0,
                            consumed_at=None,
                        ),
                    )
                    if not accepted:
                        continue
                stored = True
                break
            except DuplicateRecord:
                continue
        if not stored:
            raise VerificationError("CONCURRENT_UPDATE")
        try:
            self._sender.send_code(email, purpose, code)
        except Exception:
            self._invalidate(identifier)
            # Sanitized metric only: no email, code, or SMTP detail is logged.
            _logger.warning("Verification email delivery failed (purpose=%s)", purpose)
            raise VerificationError("SEND_FAILED") from None

    def _invalidate(self, identifier):
        for _ in range(self._attempts):
            now = self._now()
            current = self._repository.get_verification_code(identifier)
            if current is None or current.consumed_at is not None:
                return
            if self._repository.compare_and_swap_verification_code(
                identifier,
                current.version,
                self._candidate(current, now, consumed_at=now),
            ):
                return
        raise VerificationError("DEPENDENCY_UNAVAILABLE")

    @_storage_errors
    def consume(self, email: str, purpose: str, code: str) -> None:
        email = self._validated(email, purpose)
        if (
            type(code) is not str
            or len(code) != 6
            or not code.isascii()
            or not code.isdigit()
        ):
            raise VerificationError("INVALID_CODE")
        expected = verification_digest(self._secret, email, purpose, code)
        identifier = code_id(email, purpose)
        for _ in range(self._attempts):
            current = self._repository.get_verification_code(identifier)
            if current is None:
                raise VerificationError("INVALID_CODE")
            now = self._now()
            if now < current.updated_at:
                raise VerificationError("CLOCK_ERROR")
            if now >= current.expires_at:
                raise VerificationError("CODE_EXPIRED")
            if current.consumed_at is not None:
                raise VerificationError("INVALID_CODE")
            if current.attempts >= self._max_verify:
                raise VerificationError("CODE_LOCKED")
            if not digests_equal(current.digest, expected):
                accepted = self._repository.compare_and_swap_verification_code(
                    identifier,
                    current.version,
                    self._candidate(current, now, attempts=current.attempts + 1),
                )
                if accepted:
                    raise VerificationError("INVALID_CODE")
                continue
            accepted = self._repository.compare_and_swap_verification_code(
                identifier,
                current.version,
                self._candidate(current, now, consumed_at=now),
            )
            if accepted:
                return
        raise VerificationError("CONCURRENT_UPDATE")
