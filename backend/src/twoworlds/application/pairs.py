"""Invitation workflows; ownership comes from a previously authenticated account."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import wraps
import secrets
from typing import Callable, Literal

from pydantic import TypeAdapter

from twoworlds.domain.persistence import PairRecord, UTCDateTime
from twoworlds.ports.repository import DuplicateRecord, Repository, RepositoryError
from twoworlds.security.credentials import digest_secret, new_secret


class PairError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(
            {
                "INVITE_INVALID": "邀请凭证无效。",
                "PAIR_NOT_FOUND": "房间不存在或无法访问。",
                "PAIR_FULL": "房间已满员。",
                "CONCURRENT_UPDATE": "房间更新竞争，请重试。",
                "DEPENDENCY_UNAVAILABLE": "房间存储暂不可用。",
                "GENERATION_FAILED": "无法生成新的邀请凭证。",
                "CLOCK_ERROR": "房间服务时间无效。",
            }[code]
        )


@dataclass(frozen=True)
class InvitationIssued:
    id: str
    invite_expires_at: datetime
    invite_token: str = field(repr=False)


@dataclass(frozen=True)
class PairInfo:
    id: str
    role: Literal["a", "b"]
    member_count: int


def _storage_errors(method):
    @wraps(method)
    def wrapped(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except RepositoryError:
            raise PairError("DEPENDENCY_UNAVAILABLE") from None

    return wrapped


class PairService:
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
        self._repository, self._clock = repository, clock
        self._generator, self._attempts = credential_generator, max_attempts

    def _now(self, pair=None):
        try:
            now = TypeAdapter(UTCDateTime).validate_python(self._clock())
        except Exception:
            raise PairError("CLOCK_ERROR") from None
        if pair is not None and now < pair.updated_at:
            raise PairError("CLOCK_ERROR")
        return now

    @staticmethod
    def _expiry(now):
        try:
            return now + timedelta(hours=24)
        except OverflowError:
            raise PairError("CLOCK_ERROR") from None

    def _invite(self):
        try:
            token = new_secret("invite", self._generator)
            return token, digest_secret(token, "invite")
        except Exception:
            raise PairError("GENERATION_FAILED") from None

    @staticmethod
    def _info(pair, actor_id):
        if actor_id == pair.member_a:
            role = "a"
        elif actor_id == pair.member_b:
            role = "b"
        else:
            raise PairError("PAIR_NOT_FOUND")
        return PairInfo(pair.id, role, 1 if pair.member_b is None else 2)

    @_storage_errors
    def create_pair(self, actor_id: str) -> InvitationIssued:
        if self._repository.get_account(actor_id) is None:
            raise PairError("PAIR_NOT_FOUND")
        for _ in range(self._attempts):
            now = self._now()
            expires = self._expiry(now)
            token, digest = self._invite()
            candidate = PairRecord(
                id="pair_" + secrets.token_hex(16),
                member_a=actor_id,
                invite_digest=digest,
                invite_expires_at=expires,
                created_at=now,
                updated_at=now,
            )
            try:
                saved = self._repository.create_pair(candidate)
            except DuplicateRecord:
                continue
            return InvitationIssued(saved.id, saved.invite_expires_at, token)
        raise PairError("GENERATION_FAILED")

    @_storage_errors
    def refresh_invite(self, actor_id: str, pair_id: str) -> InvitationIssued:
        conflicted = False
        for _ in range(self._attempts):
            current = self._repository.get_pair(pair_id)
            if current is None or current.member_a != actor_id:
                raise PairError("PAIR_NOT_FOUND")
            if current.member_b is not None:
                raise PairError("PAIR_FULL")
            now = self._now(current)
            expires = self._expiry(now)
            token, digest = self._invite()
            if digest == current.invite_digest:
                continue
            candidate = PairRecord.model_validate(
                current.model_dump()
                | {
                    "invite_digest": digest,
                    "invite_expires_at": expires,
                    "updated_at": now,
                    "version": current.version + 1,
                }
            )
            try:
                accepted = self._repository.compare_and_swap_pair(
                    pair_id, current.version, candidate
                )
            except DuplicateRecord:
                continue
            if accepted:
                return InvitationIssued(pair_id, expires, token)
            conflicted = True
        raise PairError("CONCURRENT_UPDATE" if conflicted else "GENERATION_FAILED")

    @_storage_errors
    def join_pair(self, actor_id: str, invite_token: str) -> PairInfo:
        try:
            digest = digest_secret(invite_token, "invite")
        except ValueError:
            raise PairError("INVITE_INVALID") from None
        for _ in range(self._attempts):
            current = self._repository.get_pair_by_invite_digest(digest)
            if current is None or current.member_a == actor_id:
                raise PairError("INVITE_INVALID")
            now = self._now(current)
            # Membership is permanent in T07. Replaying an accepted invitation is
            # a read, even after expiry; no expired invitation can claim a new slot.
            if current.member_b == actor_id:
                return self._info(current, actor_id)
            if current.member_b is not None:
                raise PairError("PAIR_FULL")
            if now >= current.invite_expires_at:
                raise PairError("INVITE_INVALID")
            accepted = self._repository.join_pair(current.id, actor_id, digest, now)
            if accepted is not None:
                return self._info(accepted, actor_id)
            # A refresh or another join won. Re-read the invitation, never infer
            # success or overwrite the winner from this stale record.
        raise PairError("CONCURRENT_UPDATE")

    @_storage_errors
    def list_pairs(self, actor_id: str) -> tuple[PairInfo, ...]:
        return tuple(
            self._info(pair, actor_id)
            for pair in self._repository.list_pairs_for_member(actor_id)
        )
