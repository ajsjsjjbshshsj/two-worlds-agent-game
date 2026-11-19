from fastapi import APIRouter, Request

from twoworlds.api.limits import check_limits, client_ip, digest_key
from twoworlds.api.schemas.identity import CodeAccepted, RequestCode

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
    # Delivery is scheduled in the background; send failures never surface here
    # and never reveal whether the address exists.
    request.app.state.verification_service.request_code(body.email, body.purpose)
    return CodeAccepted()
