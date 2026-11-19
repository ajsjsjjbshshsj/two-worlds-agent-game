from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from twoworlds.application.identity import IdentityError
from twoworlds.application.commands import CommandError
from twoworlds.application.pairs import PairError
from twoworlds.application.rate_limit import RateLimitError
from twoworlds.application.saves import SaveError
from twoworlds.application.verification import VerificationError

_STATUS = {
    "UNAUTHENTICATED": 401,
    "INVALID_CREDENTIALS": 401,
    "INVALID_INPUT": 422,
    "EMAIL_ALREADY_REGISTERED": 409,
    "CONCURRENT_UPDATE": 409,
    "DEPENDENCY_UNAVAILABLE": 503,
    "GENERATION_FAILED": 503,
    "CLOCK_ERROR": 503,
}


def failure(status, code, message, retryable=False, headers=None):
    return JSONResponse(
        {"error": {"code": code, "message": message, "retryable": retryable}},
        status_code=status,
        headers={"Cache-Control": "no-store", **(headers or {})},
    )


async def identity_error(request, error):
    status = _STATUS[error.code]
    return failure(status, error.code, str(error), status in {409, 503})


async def verification_error(request, error):
    status = {
        "INVALID_INPUT": 422,
        "INVALID_CODE": 422,
        "CODE_EXPIRED": 422,
        "CODE_LOCKED": 422,
        "SEND_FAILED": 503,
    }.get(error.code, _STATUS.get(error.code, 503))
    return failure(status, error.code, str(error), status in {409, 503})


async def rate_limit_error(request, error):
    if error.code == "RATE_LIMITED":
        return failure(
            429,
            "RATE_LIMITED",
            str(error),
            True,
            {"Retry-After": str(error.retry_after)},
        )
    status = _STATUS.get(error.code, 503)
    return failure(status, error.code, str(error), status in {409, 503})


async def invalid_request(request, error):
    # Never serialize error.errors(): it includes the original credential input.
    return failure(422, "INVALID_INPUT", "身份输入无效。")


async def pair_error(request, error):
    status = {"INVITE_INVALID": 404, "PAIR_NOT_FOUND": 404, "PAIR_FULL": 409}.get(
        error.code, _STATUS.get(error.code, 503)
    )
    return failure(
        status,
        error.code,
        str(error),
        error.code
        in {
            "CONCURRENT_UPDATE",
            "DEPENDENCY_UNAVAILABLE",
            "GENERATION_FAILED",
            "CLOCK_ERROR",
        },
    )


async def http_error(request, error):
    code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(
        error.status_code, "HTTP_ERROR"
    )
    return failure(error.status_code, code, "请求无法处理。", headers=error.headers)


async def save_error(request, error):
    status = {
        "SAVE_NOT_FOUND": 404,
        "MEDIA_NOT_FOUND": 404,
        "SCRIPT_NOT_FOUND": 404,
        "SCRIPT_VERSION_CONFLICT": 409,
        "SCRIPT_UNSUPPORTED": 409,
    }.get(error.code, 503)
    return failure(status, error.code, str(error), status == 503)


def install_handlers(app):
    app.add_exception_handler(IdentityError, identity_error)
    app.add_exception_handler(VerificationError, verification_error)
    app.add_exception_handler(RateLimitError, rate_limit_error)
    app.add_exception_handler(PairError, pair_error)
    app.add_exception_handler(SaveError, save_error)
    app.add_exception_handler(CommandError, command_error)
    app.add_exception_handler(RequestValidationError, invalid_request)
    app.add_exception_handler(HTTPException, http_error)


async def command_error(request, error):
    status = (
        409
        if error.code
        in {
            "VERSION_CONFLICT",
            "REQUEST_ID_REUSED",
            "SAVE_COMMAND_LIMIT",
        }
        else 422
    )
    return failure(status, error.code, str(error))
