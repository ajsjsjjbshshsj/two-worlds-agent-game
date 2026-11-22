"""Fixed transport outcomes that can safely cross into the narrative graph."""

from enum import StrEnum

from twoworlds.ai.providers.usage import Usage


class FailureKind(StrEnum):
    AUTHENTICATION = "provider_authentication"
    FORBIDDEN = "provider_forbidden"
    TIMEOUT = "provider_timeout"
    RATE_LIMIT = "provider_rate_limit"
    UNAVAILABLE = "provider_unavailable_http"
    REDIRECT = "provider_redirect"
    HTTP = "provider_http_error"
    TRANSPORT = "provider_transport_error"
    RESPONSE = "provider_invalid_response"
    USAGE = "provider_invalid_usage"
    INPUT_LIMIT = "provider_input_limit"


class ProviderFailure(RuntimeError):
    def __init__(self, kind: FailureKind, usage: Usage | None = None):
        self.kind = kind
        self.usage = usage
        super().__init__(kind.value)
