"""ASGI WebSocket adapter for the authenticated save subscription."""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

from twoworlds.api.auth import session_token
from twoworlds.application.identity import IdentityError
from twoworlds.application.saves import SaveError
from twoworlds.realtime.protocol import CloseCode, ConnectionRejected
from twoworlds.realtime.subscriptions import serve_subscription


router = APIRouter()


@router.websocket("/api/ws/saves/{save_id}")
async def save_socket(websocket: WebSocket, save_id: str):
    state = websocket.app.state
    origins = websocket.headers.getlist("origin")
    if (
        len(origins) != 1
        or origins[0] not in state.allowed_origins
        or websocket.scope.get("query_string")
    ):
        await websocket.close(CloseCode.INVALID_HANDSHAKE)
        return

    async def receive_text():
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            raise WebSocketDisconnect(message["code"])
        frame = message.get("text")
        if frame is None:
            raise ConnectionRejected(CloseCode.INVALID_MESSAGE)
        return frame

    try:
        token = session_token(websocket)
        account_id = (
            await run_in_threadpool(state.identity_service.authenticate, token)
        ).id
        try:
            snapshot = await run_in_threadpool(
                state.save_service.read_save, account_id, save_id
            )
        except SaveError as error:
            if error.code != "SAVE_NOT_FOUND":
                raise
            # An authenticated caller gets the same protocol close for both cases.
            await websocket.accept()
            await websocket.close(CloseCode.SAVE_NOT_FOUND)
            return

        await websocket.accept()
        await websocket.send_json(
            {"type": "snapshot", "save": snapshot.model_dump(mode="json")}
        )
        del snapshot
        await serve_subscription(
            receive=receive_text,
            send=websocket.send_json,
            token=token,
            account_id=account_id,
            identity=state.identity_service,
            timing=state.websocket_timing,
        )
        return
    except WebSocketDisconnect:
        return
    except ConnectionRejected as error:
        code = error.code
    except IdentityError as error:
        code = (
            CloseCode.UNAUTHENTICATED
            if error.code == "UNAUTHENTICATED"
            else CloseCode.INTERNAL_ERROR
        )
    except Exception:
        # Error text and frame contents can contain credentials. Send a code only.
        code = CloseCode.INTERNAL_ERROR

    try:
        await websocket.close(code)
    except WebSocketDisconnect:
        pass
