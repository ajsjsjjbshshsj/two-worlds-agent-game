"""ASGI WebSocket adapter for the authenticated save subscription."""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from twoworlds.application.identity import IdentityError
from twoworlds.realtime.protocol import CloseCode, ConnectionRejected
from twoworlds.realtime.subscriptions import serve_subscription


router = APIRouter()


@router.websocket("/api/ws/saves/{save_id}")
async def save_socket(websocket: WebSocket, save_id: str):
    state = websocket.app.state
    origins = websocket.headers.getlist("origin")
    # Deny before Upgrade. No query parameters are part of the WS protocol.
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
        text = message.get("text")
        if text is None:
            raise ConnectionRejected(CloseCode.INVALID_MESSAGE)
        return text

    try:
        await websocket.accept()
        await serve_subscription(
            receive=receive_text,
            send=websocket.send_json,
            save_id=save_id,
            identity=state.identity_service,
            saves=state.save_service,
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
