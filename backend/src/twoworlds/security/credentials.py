"""256-bit random credentials with separate recovery, session and invite namespaces."""

from hashlib import sha256
import re
import secrets

_PREFIX = {"recovery": "tw_recovery_", "session": "tw_session_", "invite": "tw_invite_"}
_RANDOM = re.compile(r"[A-Za-z0-9_-]{43}\Z")


def new_secret(kind: str, generator=None) -> str:
    value = secrets.token_urlsafe(32) if generator is None else generator()
    if type(value) is not str or not _RANDOM.fullmatch(value):
        raise ValueError("Credential generator returned an invalid value")
    return _PREFIX[kind] + value


def digest_secret(value: str, kind: str | None = None) -> str:
    kinds = (kind,) if kind is not None else tuple(_PREFIX)
    if type(value) is not str or not any(
        value.startswith(_PREFIX[k]) and _RANDOM.fullmatch(value[len(_PREFIX[k]) :])
        for k in kinds
    ):
        raise ValueError("Invalid credential")
    return sha256(value.encode("ascii")).hexdigest()
