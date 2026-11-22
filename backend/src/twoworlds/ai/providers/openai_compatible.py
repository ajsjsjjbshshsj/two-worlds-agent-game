"""Server-side Chat Completions transport. No tools, redirects or retries."""

import asyncio
import json

import httpx
from pydantic import ValidationError

from twoworlds.ai.prompts.npc import SYSTEM_PROMPTS
from twoworlds.ai.providers.base import FailureKind, ProviderFailure
from twoworlds.ai.providers.config import ProviderConfig
from twoworlds.ai.providers.usage import parse_usage
from twoworlds.ports.narrative import (
    NarrativeProvider,
    NarrativeRequest,
    NarrativeResponse,
)

_MAX_RESPONSE_BYTES = 65536
_STATUS = {
    401: FailureKind.AUTHENTICATION,
    403: FailureKind.FORBIDDEN,
    408: FailureKind.TIMEOUT,
    429: FailureKind.RATE_LIMIT,
}


def _status(status):
    if 300 <= status < 400:
        return FailureKind.REDIRECT
    if 500 <= status < 600:
        return FailureKind.UNAVAILABLE
    return _STATUS.get(status, FailureKind.HTTP)


def _object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("Duplicate JSON key")
        obj[key] = value
    return obj


def _constant(_):
    raise ValueError("Invalid JSON constant")


class OpenAICompatibleProvider(NarrativeProvider):
    provider_name = "openai_compatible"
    mode = "provider"

    def __init__(
        self,
        config: ProviderConfig,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.config = config
        self._transport = transport

    def _payload(self, request):
        try:
            return json.dumps(
                {
                    "model": self.config.model,
                    "max_tokens": self.config.max_output_tokens,
                    "messages": [
                        {
                            "role": "system",
                            "content": "Prompt "
                            + request.prompt_version
                            + "\n"
                            + SYSTEM_PROMPTS[request.prompt_version],
                        },
                        {"role": "user", "content": request.context.model_dump_json()},
                    ],
                },
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (KeyError, ValueError):
            raise ProviderFailure(FailureKind.INPUT_LIMIT) from None

    def fits_input(self, request: NarrativeRequest):
        try:
            return (
                self._input_bound(self._payload(request))
                <= self.config.max_input_tokens
            )
        except ProviderFailure:
            return False

    @staticmethod
    def _input_bound(payload: bytes):
        # Conservative byte-token ceiling for this protocol plus chat framing.
        # Used only to reject oversized calls. It is never recorded as usage.
        return len(payload) + 256

    async def _send(self, payload):
        seconds = self.config.timeout
        timeout = httpx.Timeout(
            connect=min(seconds, 1),
            read=seconds,
            write=min(seconds, 1),
            pool=min(seconds, 0.5),
        )
        try:
            async with asyncio.timeout(seconds):
                async with httpx.AsyncClient(
                    timeout=timeout,
                    follow_redirects=False,
                    trust_env=False,
                    transport=self._transport,
                ) as client:
                    async with client.stream(
                        "POST",
                        self.config.endpoint,
                        content=payload,
                        headers={
                            "Authorization": "Bearer " + self.config.api_key,
                            "Content-Type": "application/json",
                            "Accept": "application/json",
                            "Accept-Encoding": "identity",
                        },
                    ) as response:
                        if response.status_code != 200:
                            raise ProviderFailure(_status(response.status_code))
                        if (
                            response.headers.get("Content-Encoding", "identity").lower()
                            != "identity"
                        ):
                            raise ProviderFailure(FailureKind.RESPONSE)
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            if len(body) + len(chunk) > _MAX_RESPONSE_BYTES:
                                raise ProviderFailure(FailureKind.RESPONSE)
                            body.extend(chunk)
                        return bytes(body)
        except (TimeoutError, httpx.TimeoutException):
            raise ProviderFailure(FailureKind.TIMEOUT) from None
        except httpx.HTTPError:
            raise ProviderFailure(FailureKind.TRANSPORT) from None

    def generate(self, request: NarrativeRequest) -> NarrativeResponse:
        payload = self._payload(request)
        if self._input_bound(payload) > self.config.max_input_tokens:
            raise ProviderFailure(FailureKind.INPUT_LIMIT)
        try:
            obj = json.loads(
                asyncio.run(self._send(payload)),
                object_pairs_hook=_object,
                parse_constant=_constant,
            )
            if type(obj) is not dict:
                raise ValueError
        except (ValueError, RecursionError):
            raise ProviderFailure(FailureKind.RESPONSE) from None
        try:
            usage = parse_usage(obj.get("usage"))
        except ValueError:
            raise ProviderFailure(FailureKind.USAGE) from None
        try:
            choices = obj["choices"]
            if type(choices) is not list or len(choices) != 1:
                raise ValueError
            choice = choices[0]
            message = choice["message"]
            if (
                type(choice) is not dict
                or type(message) is not dict
                or message.get("role", "assistant") != "assistant"
                or message.get("tool_calls")
                or message.get("function_call")
                or choice.get("finish_reason") not in {None, "stop"}
            ):
                raise ValueError
            if type(message["content"]) is not str:
                raise ValueError
            message["content"].encode("utf-8")
            return NarrativeResponse(
                text=message["content"],
                mode=self.mode,
                provider_name=self.provider_name,
                prompt_version=request.prompt_version,
                usage=usage.as_dict() if usage else {},
            )
        except (KeyError, TypeError, ValueError, ValidationError):
            raise ProviderFailure(FailureKind.RESPONSE, usage) from None
