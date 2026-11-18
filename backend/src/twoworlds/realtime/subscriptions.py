"""One authenticated subscription, scoped to the lifetime of its connection."""

import asyncio
from collections.abc import Awaitable, Callable
from itertools import count

from starlette.concurrency import run_in_threadpool

from twoworlds.application.identity import IdentityService
from twoworlds.application.saves import SaveError, SaveService

from .protocol import (
    CloseCode,
    ConnectionRejected,
    WebSocketTiming,
    auth_token,
    require_pong,
)


async def serve_subscription(
    *,
    receive: Callable[[], Awaitable[str]],
    send: Callable[[dict], Awaitable[None]],
    save_id: str,
    identity: IdentityService,
    saves: SaveService,
    timing: WebSocketTiming,
) -> None:
    try:
        async with asyncio.timeout(timing.auth_timeout):
            token = auth_token(await receive())
            account_id = (await run_in_threadpool(identity.authenticate, token)).id
            # Identical authorization, pinned content and projection to HTTP GET.
            snapshot = await run_in_threadpool(saves.read_save, account_id, save_id)
    except TimeoutError:
        raise ConnectionRejected(CloseCode.UNAUTHENTICATED) from None
    except SaveError as error:
        if error.code == "SAVE_NOT_FOUND":
            raise ConnectionRejected(CloseCode.SAVE_NOT_FOUND) from None
        raise

    await send({"type": "snapshot", "save": snapshot.model_dump(mode="json")})
    del snapshot
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
