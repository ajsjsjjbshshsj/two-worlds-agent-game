from fastapi import APIRouter, Request, Response

from twoworlds.api.cookies import clear_session_cookie
from twoworlds.api.schemas.identity import ResetPassword

router = APIRouter()


@router.post("/api/password-resets", status_code=204)
def reset_password(body: ResetPassword, request: Request):
    state = request.app.state
    state.verification_service.consume(body.email, "reset", body.code)
    state.identity_service.reset_password(body.email, body.new_password)
    result = Response(status_code=204)
    clear_session_cookie(result, secure=state.cookie_secure)
    return result
