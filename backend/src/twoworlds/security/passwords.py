"""Argon2id password hashing with the parameters fixed in docs/03 §5.

Plaintext passwords never leave this module's callers; only encoded hashes are
stored. A one-time dummy hash lets login burn the same work for unknown emails,
so account existence is not revealed by response timing.
"""

import secrets
from typing import Annotated

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError
from pydantic import StrictStr, StringConstraints

MEMORY_COST = 65536
TIME_COST = 3
PARALLELISM = 4

# Plaintext bound only; never stripped or truncated, never stored or logged.
Password = Annotated[StrictStr, StringConstraints(min_length=10, max_length=128)]

_HASHER = PasswordHasher(
    memory_cost=MEMORY_COST,
    time_cost=TIME_COST,
    parallelism=PARALLELISM,
    type=Type.ID,
)
_DUMMY_HASH = _HASHER.hash(secrets.token_urlsafe(32))


def hash_password(password: str) -> str:
    return _HASHER.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _HASHER.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _HASHER.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def dummy_verify(password: str) -> None:
    try:
        _HASHER.verify(_DUMMY_HASH, password)
    except (VerificationError, InvalidHashError):
        pass
