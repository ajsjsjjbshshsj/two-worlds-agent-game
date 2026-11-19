"""Single-use email verification codes with atomic attempt/consume transitions.

Delivery runs on an in-process background executor: the HTTP response never
waits for the mail transport, so response timing does not reveal whether the
address exists. Reliability limit: pending sends live only in this process;
a crash or an unflushed shutdown loses them (and their failure invalidation).
This is not a durable email queue.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from functools import partial, wraps
from hashlib import sha256
import logging
import secrets
from threading import Condition
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


class CodeDelivery:
    """Background delivery so the HTTP response never waits for SMTP.

    Failure of a send invalidates only that issuance (by issue id) and is
    logged sanitized. ``close`` waits for in-flight sends; anything still
    queued when the process dies is lost by design — see the module docstring.
    """

    def __init__(self, sender: EmailCodeSender, *, max_workers: int = 4):
        if type(max_workers) is not int or max_workers < 1:
            raise ValueError("max_workers must be a positive integer")
        self._sender = sender
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="twoworlds-email"
        )
        self._condition = Condition()
        self._outstanding = 0
        self._closed = False

    def submit(self, email: str, purpose: str, code: str, *, on_failure) -> None:
        with self._condition:
            if self._closed:
                raise RuntimeError("code delivery is closed")
            self._outstanding += 1
        try:
            self._executor.submit(self._run, email, purpose, code, on_failure)
        except RuntimeError:
            self._finish()
            raise

    def _run(self, email, purpose, code, on_failure):
        try:
            self._sender.send_code(email, purpose, code)
        except Exception:
            # Sanitized metric only: no email, code, or SMTP detail is logged.
            _logger.warning("Verification email delivery failed (purpose=%s)", purpose)
            try:
                on_failure()
            except Exception:
                _logger.warning(
                    "Verification code invalidation failed (purpose=%s)", purpose
                )
        finally:
            self._finish()

    def _finish(self):
        with self._condition:
            self._outstanding -= 1
            self._condition.notify_all()

    def wait(self, timeout: float | None = None) -> bool:
        with self._condition:
            return self._condition.wait_for(lambda: self._outstanding == 0, timeout)

    def close(self):
        with self._condition:
            self._closed = True
        self._executor.shutdown(wait=True)


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
        self._delivery = CodeDelivery(sender)
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
        # Unknown reset addresses take the same store-and-respond path; only the
        # background delivery differs and it never leaves the server for them.
        deliver = purpose == "register" or (
            self._repository.get_account_by_email(email) is not None
        )
        code = self._code()
        issue_id = secrets.token_hex(16)
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
                            issue_id=issue_id,
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
                    # Resend replaces the old digest and issue id: the previous
                    # code dies, and any of its pending sends can no longer
                    # invalidate this one.
                    accepted = self._repository.compare_and_swap_verification_code(
                        identifier,
                        current.version,
                        self._candidate(
                            current,
                            now,
                            issue_id=issue_id,
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
        if not deliver:
            return
        try:
            self._delivery.submit(
                email,
                purpose,
                code,
                on_failure=partial(self._invalidate, identifier, issue_id),
            )
        except RuntimeError:
            # Delivery is closed (shutdown); this code can never be received.
            _logger.warning("Verification email delivery failed (purpose=%s)", purpose)
            self._invalidate(identifier, issue_id)

    def wait_for_delivery(self, timeout: float | None = None) -> bool:
        return self._delivery.wait(timeout)

    def close(self):
        self._delivery.close()

    def _invalidate(self, identifier, issue_id):
        for _ in range(self._attempts):
            now = self._now()
            current = self._repository.get_verification_code(identifier)
            if current is None or current.consumed_at is not None:
                return
            if current.issue_id != issue_id:
                # A newer issuance replaced this one; its code must stay usable.
                return
            if self._repository.compare_and_swap_verification_code(
                identifier,
                current.version,
                self._candidate(current, now, consumed_at=now),
            ):
                return
        _logger.warning("Verification code invalidation gave up after contention")

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
