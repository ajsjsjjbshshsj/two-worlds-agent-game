from fastapi import APIRouter, Request

from twoworlds.api.schemas.identity import (
    CreateAccount,
    CreatedIdentity,
    SessionCredential,
    account_view,
)

router = APIRouter()


@router.post("/api/accounts", response_model=CreatedIdentity)
def create_account(body: CreateAccount, request: Request):
    result = request.app.state.identity_service.create_account(body.display_name)
    return CreatedIdentity(
        account=account_view(result.account),
        recovery_key=result.recovery_key,
        session=SessionCredential(token=result.token, expires_at=result.expires_at),
    )
