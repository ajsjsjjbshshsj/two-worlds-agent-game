"""Trusted response usage and exact USD micro-unit arithmetic."""

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int
    total_tokens: int

    def as_dict(self):
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }


def _tokens(value):
    return type(value) is int and 0 <= value <= 10**9


def parse_usage(raw) -> Usage | None:
    if raw is None:
        return None
    fields = ("prompt_tokens", "completion_tokens", "total_tokens")
    details = {
        "prompt_tokens_details": {"cached_tokens", "audio_tokens"},
        "completion_tokens_details": {
            "reasoning_tokens",
            "audio_tokens",
            "accepted_prediction_tokens",
            "rejected_prediction_tokens",
        },
    }
    if type(raw) is not dict or set(raw) - set(fields) - details.keys():
        raise ValueError("Invalid usage")
    if not all(_tokens(raw.get(key)) for key in fields):
        raise ValueError("Invalid usage")
    for key, allowed in details.items():
        detail = raw.get(key)
        if detail is not None and (
            type(detail) is not dict
            or set(detail) - allowed
            or not all(_tokens(value) for value in detail.values())
        ):
            raise ValueError("Invalid usage")
    usage = Usage(*(raw[key] for key in fields))
    if usage.input_tokens + usage.output_tokens != usage.total_tokens:
        raise ValueError("Invalid usage total")
    return usage


@dataclass(frozen=True)
class Pricing:
    version: str
    input_usd_per_million: Decimal
    output_usd_per_million: Decimal

    def micros(self, input_tokens: int, output_tokens: int) -> int:
        # USD per million tokens is numerically micro-USD per token.
        amount = (
            self.input_usd_per_million * input_tokens
            + self.output_usd_per_million * output_tokens
        )
        return int(amount.to_integral_value(rounding=ROUND_CEILING))
