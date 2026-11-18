"""Wire messages, close codes and deadlines for personal save connections."""

from dataclasses import dataclass
from enum import IntEnum
import json
from math import isfinite


MAX_CLIENT_MESSAGE_BYTES = 4096


@dataclass(frozen=True)
class WebSocketTiming:
    auth_timeout: float = 10
    heartbeat_interval: float = 10
    pong_timeout: float = 5

    def __post_init__(self):
        for value in (self.auth_timeout, self.heartbeat_interval, self.pong_timeout):
            if not isfinite(value) or value <= 0:
                raise ValueError("WebSocket deadlines must be finite and positive")


class CloseCode(IntEnum):
    MESSAGE_TOO_BIG = 1009
    INTERNAL_ERROR = 1011
    INVALID_MESSAGE = 4400
    UNAUTHENTICATED = 4401
    INVALID_HANDSHAKE = 4403
    SAVE_NOT_FOUND = 4404
    HEARTBEAT_TIMEOUT = 4408


class ConnectionRejected(Exception):
    def __init__(self, code: CloseCode):
        self.code = code
        super().__init__(code.name)


def _unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ConnectionRejected(CloseCode.INVALID_MESSAGE)
        result[key] = value
    return result


def _read_object(text: str) -> dict:
    try:
        if len(text) > MAX_CLIENT_MESSAGE_BYTES or (
            len(text.encode("utf-8")) > MAX_CLIENT_MESSAGE_BYTES
        ):
            raise ConnectionRejected(CloseCode.MESSAGE_TOO_BIG)
        message = json.loads(text, object_pairs_hook=_unique_fields)
    except (ValueError, RecursionError):
        raise ConnectionRejected(CloseCode.INVALID_MESSAGE) from None
    if not isinstance(message, dict):
        raise ConnectionRejected(CloseCode.INVALID_MESSAGE)
    return message


def auth_token(text: str) -> str:
    message = _read_object(text)
    if (
        message.keys() != {"type", "token"}
        or message["type"] != "auth"
        or type(message["token"]) is not str
        or not message["token"]
    ):
        raise ConnectionRejected(CloseCode.INVALID_MESSAGE)
    return message["token"]


def require_pong(text: str, ping_id: int) -> None:
    message = _read_object(text)
    if (
        message.keys() != {"type", "id"}
        or message["type"] != "pong"
        or type(message["id"]) is not int
        or message["id"] != ping_id
    ):
        raise ConnectionRejected(CloseCode.INVALID_MESSAGE)
