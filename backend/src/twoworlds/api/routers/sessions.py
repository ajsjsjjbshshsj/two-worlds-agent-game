from fastapi import APIRouter, Depends, Request, Response

from twoworlds.api.auth import Authenticated, current_identity, session_token
from twoworlds.api.schemas.identity import (
    CurrentIdentity,
    RecoveredIdentity,
    RecoverSession,
    SessionCredential,
    SessionView,
    account_view,
)

router = APIRouter()


@router.post("/api/sessions/recover", response_model=RecoveredIdentity)
def recover_session(body: RecoverSession, request: Request):
    result = request.app.state.identity_service.recover(body.recovery_key)
    return RecoveredIdentity(
        account=account_view(result.account),
        session=SessionCredential(token=result.token, expires_at=result.expires_at),
    )


@router.get("/api/me", response_model=CurrentIdentity)
def me(identity: Authenticated = Depends(current_identity)):
    return CurrentIdentity(
        account=account_view(identity.account),
        session=SessionView(expires_at=identity.expires_at),
    )


@router.delete("/api/sessions/current", status_code=204)
def logout(request: Request, token: str = Depends(session_token)):
    request.app.state.identity_service.revoke(token)
    return Response(status_code=204)
