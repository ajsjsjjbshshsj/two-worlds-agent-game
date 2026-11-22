"""Revalidate provider output before any part of it is used for a save."""

from pydantic import ValidationError

from twoworlds.ports.narrative import NarrativeRequest, NarrativeResponse

_USAGE_KEYS = {"input_tokens", "output_tokens", "total_tokens"}


def validate_response(raw, request: NarrativeRequest, *, mode, provider_name):
    if isinstance(raw, NarrativeResponse):
        # Validate attributes, including extras on subclasses, rather than accepting
        # an existing Pydantic instance or silently dropping unknown fields.
        raw = vars(raw) | (raw.model_extra or {})
    if type(raw) is not dict:
        return None
    try:
        reply = NarrativeResponse.model_validate(raw, strict=True)
        reply.text.encode("utf-8")
    except (ValidationError, UnicodeError):
        return None
    if (
        reply.mode != mode
        or reply.provider_name != provider_name
        or reply.prompt_version != request.prompt_version
        or not reply.usage.keys() <= _USAGE_KEYS
        or any(value < 0 for value in reply.usage.values())
        or reply.timeout_ms is not None
        or reply.error_code is not None
    ):
        return None
    return reply
