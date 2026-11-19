"""HttpOnly session cookie helpers; set and clear use identical attributes."""

from starlette.responses import Response

SESSION_COOKIE = "tw_session"
SESSION_MAX_AGE = 604800


def set_session_cookie(response: Response, token: str, *, secure: bool) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        path="/",
        secure=secure,
    )


def clear_session_cookie(response: Response, *, secure: bool) -> None:
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        secure=secure,
        httponly=True,
        samesite="lax",
    )
