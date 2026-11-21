"""One authenticated subscription, scoped to the lifetime of its connection."""

import asyncio
from collections.abc import Awaitable, Callable

from starlette.concurrency import run_in_threadpool

from twoworlds.application.identity import IdentityService
from twoworlds.application.saves import SaveService

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
    saves: SaveService,
    save_id: str,
    version: int,
    timing: WebSocketTiming,
) -> None:
    # A single receive loop owns all timers. There is no global subscription
    # registry or detached heartbeat task to clean up on disconnect.
    loop = asyncio.get_running_loop()
    ping_at = loop.time() + timing.heartbeat_interval
    read_at = loop.time() + timing.snapshot_interval
    ping_id = 0

    async def require_current_session():
        if (await run_in_threadpool(identity.authenticate, token)).id != account_id:
            raise ConnectionRejected(CloseCode.UNAUTHENTICATED)

    while True:
        try:
            async with asyncio.timeout_at(min(ping_at, read_at)):
                await receive()
        except TimeoutError:
            pass
        else:
            # This includes attempts to change identity by authenticating again.
            raise ConnectionRejected(CloseCode.INVALID_MESSAGE)

        if loop.time() >= ping_at:
            await require_current_session()
            ping_id += 1
            try:
                async with asyncio.timeout(timing.pong_timeout):
                    await send({"type": "ping", "id": ping_id})
                    require_pong(await receive(), ping_id)
            except TimeoutError:
                raise ConnectionRejected(CloseCode.HEARTBEAT_TIMEOUT) from None
            ping_at = loop.time() + timing.heartbeat_interval

        if loop.time() >= read_at:
            snapshot = await run_in_threadpool(
                saves.read_save_after, account_id, save_id, version
            )
            if snapshot is not None:
                # A revoked connection may have committed updates waiting before its next ping.
                await require_current_session()
                async with asyncio.timeout(timing.pong_timeout):
                    await send(
                        {"type": "snapshot", "save": snapshot.model_dump(mode="json")}
                    )
                version = snapshot.version
            read_at = loop.time() + timing.snapshot_interval
