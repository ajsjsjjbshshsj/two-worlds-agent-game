"""One authenticated subscription, scoped to the lifetime of its connection."""

import asyncio
from collections.abc import Awaitable, Callable
from itertools import count

from starlette.concurrency import run_in_threadpool

from twoworlds.application.identity import IdentityService

from .protocol import (
    CloseCode,
    ConnectionRejected,
    WebSocketTiming,
    require_pong,
)


async def serve_subscription(
    *,
    receive: Callable[[], Awaitable[str]],
    send: Callable[[dict], Awaitable[None]],
    token: str,
    account_id: str,
    identity: IdentityService,
    timing: WebSocketTiming,
) -> None:
    # A single receive loop owns all timers. There is no global subscription
    # registry or detached heartbeat task to clean up on disconnect.
    for ping_id in count(1):
        try:
            async with asyncio.timeout(timing.heartbeat_interval):
                await receive()
        except TimeoutError:
            pass
        else:
            # This includes attempts to change identity by authenticating again.
            raise ConnectionRejected(CloseCode.INVALID_MESSAGE)

        if (await run_in_threadpool(identity.authenticate, token)).id != account_id:
            raise ConnectionRejected(CloseCode.UNAUTHENTICATED)
        try:
            async with asyncio.timeout(timing.pong_timeout):
                await send({"type": "ping", "id": ping_id})
                require_pong(await receive(), ping_id)
        except TimeoutError:
            raise ConnectionRejected(CloseCode.HEARTBEAT_TIMEOUT) from None
