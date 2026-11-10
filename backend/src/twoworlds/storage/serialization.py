"""Strict, deterministic JSON serialization for persisted Pydantic values."""

import json
from typing import TypeVar

from pydantic import BaseModel, ValidationError

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


def dumps(model: BaseModel) -> str:
    if not isinstance(model, BaseModel):
        raise TypeError("only Pydantic models can be persisted")
    try:
        value = json.dumps(
            model.model_dump(mode="json", warnings=False),
            ensure_ascii=False, allow_nan=False, sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError):
        raise SerializationError("model cannot be serialized as strict JSON") from None
    if len(value.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise SerializationError("document exceeds the storage size limit")
    return value


def loads(raw: str, model_type: type[ModelT]) -> ModelT:
    if type(raw) is not str or len(raw.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        raise SerializationError("stored document is invalid or oversized")
    try:
        value = json.loads(
            raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant
        )
        return model_type.model_validate(value)
    except (UnicodeError, ValueError, TypeError, RecursionError, ValidationError):
        raise SerializationError("stored document failed strict validation") from None
