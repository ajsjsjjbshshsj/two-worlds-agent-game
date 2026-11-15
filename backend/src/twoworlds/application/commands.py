"""Validated command envelope and deterministic, actor-scoped receipt views."""

import hashlib
import json
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BeforeValidator, Field, StrictInt, field_validator

from twoworlds.content.schema import ContentModel, Identifier
from twoworlds.domain.errors import DomainError


def parse_request_id(value):
    if isinstance(value, UUID):
        return value
    if type(value) is not str:
        raise ValueError("request_id must be a UUID string")
    return UUID(value)


RequestId = Annotated[UUID, BeforeValidator(parse_request_id)]
AcceptedVersion = Annotated[StrictInt, Field(gt=0)]


class GameCommand(ContentModel):
    request_id: RequestId
    expected_version: Annotated[StrictInt, Field(ge=0)]
    kind: Identifier
    args: dict[str, Any]

    @field_validator("args", mode="before")
    @classmethod
    def finite_json_object(cls, value):
        if type(value) is not dict:
            raise ValueError("args must be an object")
        try:
            # Reject non-JSON objects, NaN/Infinity and invalid Unicode before hashing.
            json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        except (TypeError, ValueError, RecursionError):
            raise ValueError("args must contain finite JSON data") from None
        return value

    def fingerprint(self) -> str:
        raw = json.dumps(
            self.model_dump(exclude={"request_id"}),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()


class AcceptedReceipt(ContentModel):
    request_id: RequestId
    status: Literal["accepted"] = "accepted"
    accepted_version: AcceptedVersion
    duplicate: bool


class ReceiptFound(ContentModel):
    accepted: Literal[True] = True
    request_id: RequestId
    accepted_version: AcceptedVersion


class ReceiptMissing(ContentModel):
    accepted: Literal[False] = False


class CommandError(RuntimeError):
    """Fixed business/rule messages, never the submitted body or raw exceptions."""

    def __init__(self, code):
        self.code = code
        message = {
            "VERSION_CONFLICT": "存档版本已变化，请重新读取后确认操作。",
            "REQUEST_ID_REUSED": "该请求标识已用于其他请求内容。",
            "SAVE_COMMAND_LIMIT": "本存档已达到命令上限，仍可读取及查询旧回执。",
            "PAIR_NOT_READY": "搭档尚未加入，暂不能推进游戏。",
        }.get(code)
        super().__init__(message if message is not None else str(DomainError(code)))
