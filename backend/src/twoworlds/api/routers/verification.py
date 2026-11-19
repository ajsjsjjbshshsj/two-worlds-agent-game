from fastapi import APIRouter, Request

from twoworlds.api.limits import check_limits, client_ip, digest_key
from twoworlds.api.schemas.identity import CodeAccepted, RequestCode
from twoworlds.application.verification import VerificationError

router = APIRouter()


@router.post("/api/verification-codes", response_model=CodeAccepted, status_code=202)
def request_code(body: RequestCode, request: Request):
    email_key = digest_key(body.email)
    check_limits(
        request,
        ("code_email_minute", f"code:email:min:{email_key}"),
        ("code_email_hour", f"code:email:hour:{email_key}"),
        ("code_ip_hour", f"code:ip:hour:{digest_key(client_ip(request))}"),
    )
    try:
        request.app.state.verification_service.request_code(body.email, body.purpose)
    except VerificationError as error:
        if error.code != "SEND_FAILED":
            raise
        # Delivery failure must not reveal whether the email is registered.
    return CodeAccepted()
