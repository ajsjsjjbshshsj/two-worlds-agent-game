from fastapi import APIRouter, Request, Response

from twoworlds.api.cookies import set_session_cookie
from twoworlds.api.schemas.identity import (
    IdentityView,
    RegisterAccount,
    SessionView,
    account_view,
)

router = APIRouter()


@router.post("/api/accounts", response_model=IdentityView)
def register(body: RegisterAccount, request: Request, response: Response):
    state = request.app.state
    # Consume first: a duplicate-email 409 may only follow a valid code.
    state.verification_service.consume(body.email, "register", body.code)
    result = state.identity_service.register(
        body.email, body.password, body.display_name
    )
    set_session_cookie(response, result.token, secure=state.cookie_secure)
    return IdentityView(
        account=account_view(result.account),
        session=SessionView(expires_at=result.expires_at),
    )
