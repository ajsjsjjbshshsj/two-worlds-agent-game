"""256-bit random session/invite credentials and keyed verification-code digests.

Session and invite secrets keep separate namespaces and are stored as SHA-256
digests. Six-digit verification codes have a tiny search space, so their digests
are HMAC-SHA256 under a server secret and compared in constant time.
"""

from hashlib import sha256
import hmac
import re
import secrets

_PREFIX = {"session": "tw_session_", "invite": "tw_invite_"}
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


def verification_digest(secret: str, email: str, purpose: str, code: str) -> str:
    if type(secret) is not str or not secret:
        raise ValueError("A non-empty server secret is required")
    message = f"{email}:{purpose}:{code}".encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, sha256).hexdigest()


def digests_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(left, right)
