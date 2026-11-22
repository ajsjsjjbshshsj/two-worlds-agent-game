"""Server-only provider configuration. Demo mode ignores provider credentials."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
import hashlib
import json
import re
from urllib.parse import urlsplit

from twoworlds.ai.providers.usage import Pricing
from twoworlds.ports.narrative import PROMPT_VERSION


class ProviderConfigError(ValueError):
    def __init__(self, name):
        super().__init__("Invalid or missing server AI setting: " + name)


@dataclass(frozen=True, repr=False)
class ProviderConfig:
    endpoint: str
    destination: str
    model: str
    api_key: str = field(repr=False)
    timeout: float
    max_input_tokens: int
    max_output_tokens: int
    max_request_micros: int
    daily_budget_micros: int
    max_daily_calls: int
    pricing: Pricing

    @property
    def disclosure(self):
        return hashlib.sha256(
            json.dumps(
                ["npc_disclosure_1", self.endpoint, self.model, PROMPT_VERSION]
            ).encode("utf-8")
        ).hexdigest()

    @property
    def reservation_micros(self):
        return self.pricing.micros(self.max_input_tokens, self.max_output_tokens)


def load_provider_config(
    environ: Mapping[str, str], *, allow_loopback_http: bool = False
) -> ProviderConfig | None:
    def get(name, default=""):
        return environ.get("TWOWORLDS_AI_" + name, default)

    def match(name, expression, default=""):
        value = get(name, default)
        if re.fullmatch(expression, value) is None:
            raise ProviderConfigError(name)
        return value

    def number(name, maximum, default=""):
        value = Decimal(match(name, r"[0-9]{1,6}(?:\.[0-9]{1,6})?", default))
        if not 0 < value <= maximum:
            raise ProviderConfigError(name)
        return value

    def integer(name, maximum, default=""):
        value = int(match(name, r"[0-9]{1,6}", default))
        if not 0 < value <= maximum:
            raise ProviderConfigError(name)
        return value

    mode = get("MODE", "demo")
    if mode == "demo":
        return None
    if mode != "provider":
        raise ProviderConfigError("MODE")
    match("PROVIDER", "openai_compatible")
    base = get("BASE_URL")
    try:
        parsed = urlsplit(base)
        local = (
            allow_loopback_http
            and parsed.scheme == "http"
            and parsed.hostname in {"127.0.0.1", "::1", "localhost"}
        )
        if (
            (parsed.scheme != "https" and not local)
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port == 0
            or len(base) > 512
            or not re.fullmatch(r"[A-Za-z0-9.:[\]-]+", parsed.netloc)
            or not re.fullmatch(r"(?:/[A-Za-z0-9_.-]+)*/?", parsed.path)
            or any(part in {".", ".."} for part in parsed.path.split("/"))
            or "?" in base
            or "#" in base
            or base != base.strip()
            or any(ord(ch) < 33 for ch in base)
        ):
            raise ValueError
    except ValueError:
        raise ProviderConfigError("BASE_URL") from None

    config = ProviderConfig(
        endpoint=base.rstrip("/") + "/chat/completions",
        destination=f"{parsed.scheme}://{parsed.netloc}",
        model=match("MODEL", r"[A-Za-z0-9][A-Za-z0-9_./:-]{0,127}"),
        api_key=match("API_KEY", r"[!-~]{1,512}"),
        timeout=float(number("TIMEOUT_SECONDS", 10, "2")),
        max_input_tokens=integer("MAX_INPUT_TOKENS", 262144),
        max_output_tokens=integer("MAX_OUTPUT_TOKENS", 8192),
        max_request_micros=int(number("MAX_REQUEST_COST_USD", 1000) * 10**6),
        daily_budget_micros=int(number("DAILY_BUDGET_USD", 100000) * 10**6),
        max_daily_calls=integer("MAX_DAILY_CALLS", 1000, "200"),
        pricing=Pricing(
            match("PRICE_VERSION", r"[a-z][a-z0-9_]{0,63}"),
            number("INPUT_USD_PER_MILLION", 10000),
            number("OUTPUT_USD_PER_MILLION", 10000),
        ),
    )
    if config.max_request_micros > config.daily_budget_micros:
        raise ProviderConfigError("MAX_REQUEST_COST_USD")
    return config
