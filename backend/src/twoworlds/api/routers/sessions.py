from fastapi import APIRouter, Depends, Request, Response

from twoworlds.api.auth import Authenticated, current_identity, session_token
from twoworlds.api.cookies import clear_session_cookie, set_session_cookie
from twoworlds.api.limits import check_limits, client_ip, digest_key
from twoworlds.api.schemas.identity import (
    IdentityView,
    Login,
    SessionView,
    account_view,
)

router = APIRouter()


@router.post("/api/sessions", response_model=IdentityView)
def login(body: Login, request: Request, response: Response):
    ip_key = digest_key(client_ip(request))
    combo = digest_key(f"{client_ip(request)}|{body.email}")
    check_limits(
        request,
        ("login_minute", f"login:min:{combo}"),
        ("login_hour", f"login:hour:{combo}"),
        # Rotating emails must not buy unlimited Argon2 attempts from one peer.
        ("login_ip_minute", f"login:ip:min:{ip_key}"),
        ("login_ip_hour", f"login:ip:hour:{ip_key}"),
    )
    state = request.app.state
    result = state.identity_service.login(body.email, body.password)
    set_session_cookie(response, result.token, secure=state.cookie_secure)
    return IdentityView(
        account=account_view(result.account),
        session=SessionView(expires_at=result.expires_at),
    )


@router.get("/api/me", response_model=IdentityView)
def me(identity: Authenticated = Depends(current_identity)):
    return IdentityView(
        account=account_view(identity.account),
        session=SessionView(expires_at=identity.expires_at),
    )


@router.delete("/api/sessions/current", status_code=204)
def logout(request: Request, token: str = Depends(session_token)):
    request.app.state.identity_service.revoke(token)
    result = Response(status_code=204)
    clear_session_cookie(result, secure=request.app.state.cookie_secure)
    return result
