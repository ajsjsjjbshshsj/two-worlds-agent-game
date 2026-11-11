"""Strict, deterministic JSON serialization for persisted Pydantic values."""

import json
from math import isfinite
from typing import TypeVar

from pydantic import BaseModel

ModelT = TypeVar("ModelT", bound=BaseModel)
MAX_DOCUMENT_BYTES = 1_000_000


class SerializationError(ValueError):
    """A stored document is oversized, malformed, ambiguous or schema-invalid."""


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value: str):
    raise ValueError(f"non-standard JSON constant: {value}")


def _finite_float(raw: str) -> float:
    value = float(raw)
    if not isfinite(value):
        raise ValueError("JSON number is outside the finite range")
    return value


def _check_document_size(raw: str) -> None:
    # A character cannot encode to fewer than one UTF-8 byte.
    if type(raw) is not str or len(raw) > MAX_DOCUMENT_BYTES:
        raise SerializationError("document is invalid or oversized")
    try:
        size = len(raw.encode("utf-8"))
    except UnicodeError:
        raise SerializationError("document contains invalid Unicode") from None
    if size > MAX_DOCUMENT_BYTES:
        raise SerializationError("document exceeds the storage size limit")


def _check_decoded_unicode(value: object) -> None:
    # JSON escapes can introduce lone surrogates after the source passed UTF-8 checks.
    if isinstance(value, str):
        value.encode("utf-8")
    elif isinstance(value, dict):
        for key, item in value.items():
            key.encode("utf-8")
            _check_decoded_unicode(item)
    elif isinstance(value, list):
        for item in value:
            _check_decoded_unicode(item)


def dumps(model: BaseModel) -> str:
    if not isinstance(model, BaseModel):
        raise TypeError("only Pydantic models can be persisted")
    try:
        # Frozen models can still be produced by model_copy or model_construct.
        validated = type(model).model_validate(
            model.model_dump(mode="python", warnings=False)
        )
        value = json.dumps(
            validated.model_dump(mode="json"),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError, RecursionError):
        raise SerializationError("model cannot be serialized as strict JSON") from None
    _check_document_size(value)
    return value


def loads(raw: str, model_type: type[ModelT]) -> ModelT:
    _check_document_size(raw)
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
            parse_float=_finite_float,
        )
        _check_decoded_unicode(value)
        return model_type.model_validate(value)
    except (ValueError, TypeError, RecursionError):
        raise SerializationError("stored document failed strict validation") from None
