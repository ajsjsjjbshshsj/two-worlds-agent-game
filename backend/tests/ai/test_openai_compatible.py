from dataclasses import replace
import asyncio
import json
import logging

import httpx
import pytest

from tests.ai.test_graph import request_for
from twoworlds.ai.providers.base import FailureKind, ProviderFailure
from twoworlds.ai.providers.config import ProviderConfigError, load_provider_config
from twoworlds.ai.providers.openai_compatible import OpenAICompatibleProvider
from twoworlds.ai.providers.usage import Usage


TEST_KEY = "TEST_ONLY_SYNTHETIC_GATEWAY_CREDENTIAL"
TEST_ENV = {
    "TWOWORLDS_AI_MODE": "provider",
    "TWOWORLDS_AI_PROVIDER": "openai_compatible",
    "TWOWORLDS_AI_BASE_URL": "https://gateway.test/v1",
    "TWOWORLDS_AI_MODEL": "test-fixture-only",
    "TWOWORLDS_AI_API_KEY": TEST_KEY,
    "TWOWORLDS_AI_MAX_INPUT_TOKENS": "4096",
    "TWOWORLDS_AI_MAX_OUTPUT_TOKENS": "128",
    "TWOWORLDS_AI_MAX_REQUEST_COST_USD": "0.01",
    "TWOWORLDS_AI_DAILY_BUDGET_USD": "0.1",
    "TWOWORLDS_AI_PRICE_VERSION": "test_prices_v1",
    "TWOWORLDS_AI_INPUT_USD_PER_MILLION": "0.5",
    "TWOWORLDS_AI_OUTPUT_USD_PER_MILLION": "2",
}

USAGE_BODY = {"prompt_tokens": 17, "completion_tokens": 3, "total_tokens": 20}


def example_reply(**overrides):
    return {
        "choices": [
            {
                "message": {"role": "assistant", "content": "TEST_ONLY_NPC_REPLY"},
                "finish_reason": "stop",
            },
        ],
        "usage": USAGE_BODY,
        **overrides,
    }


def settings(**overrides):
    return load_provider_config(TEST_ENV | overrides)


def transport_with(config, handler):
    return OpenAICompatibleProvider(config, transport=httpx.MockTransport(handler))


def test_mock_chat_completions_protocol_and_no_private_logs(caplog):
    requests = []

    def handle(req):
        requests.append(req)
        return httpx.Response(200, json=example_reply())

    with caplog.at_level(logging.INFO):
        result = transport_with(settings(), handle).generate(request_for())
    assert len(requests) == 1
    req = requests[0]
    assert (
        req.method == "POST"
        and str(req.url) == "https://gateway.test/v1/chat/completions"
    )
    assert req.headers["authorization"] == "Bearer " + TEST_KEY
    assert "cookie" not in req.headers
    body = json.loads(req.content)
    assert set(body) == {"model", "max_tokens", "messages"}
    assert body["model"] == "test-fixture-only" and body["max_tokens"] == 128
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert "不可信" in body["messages"][0]["content"]
    assert json.loads(
        body["messages"][1]["content"]
    ) == request_for().context.model_dump(mode="json")
    assert result.mode == "provider" and result.provider_name == "openai_compatible"
    assert result.text == "TEST_ONLY_NPC_REPLY"
    assert result.usage == Usage(17, 3, 20).as_dict()
    assert settings().pricing.micros(17, 3) == 15
    for forbidden in (TEST_KEY, "SENSITIVE_PLAYER_QUESTION", "TEST_ONLY_NPC_REPLY"):
        assert forbidden not in caplog.text
    assert TEST_KEY.encode() not in req.content


@pytest.mark.parametrize(
    "status,kind",
    [
        (301, FailureKind.REDIRECT),
        (307, FailureKind.REDIRECT),
        (401, FailureKind.AUTHENTICATION),
        (403, FailureKind.FORBIDDEN),
        (408, FailureKind.TIMEOUT),
        (429, FailureKind.RATE_LIMIT),
        (500, FailureKind.UNAVAILABLE),
        (502, FailureKind.UNAVAILABLE),
        (503, FailureKind.UNAVAILABLE),
        (504, FailureKind.UNAVAILABLE),
    ],
)
def test_failure_never_redirects_retries_or_leaks_vendor_body(status, kind):
    requests = []

    def handle(req):
        requests.append(req)
        return httpx.Response(
            status,
            text="PRIVATE_VENDOR_BODY",
            headers={"Location": "https://forbidden.test/path"},
        )

    with pytest.raises(ProviderFailure) as raised:
        transport_with(settings(), handle).generate(request_for())
    assert raised.value.kind == kind and raised.value.usage is None
    assert "PRIVATE_VENDOR_BODY" not in str(raised.value) and TEST_KEY not in str(
        raised.value
    )
    assert len(requests) == 1


@pytest.mark.parametrize(
    "body",
    [
        b"<html>no JSON</html>",
        b'{"choices": []',
        b'{"choices":[],"choices":[]}',
        b"x" * 65537,
        json.dumps([]).encode(),
        json.dumps(example_reply(choices=[])).encode(),
        json.dumps(example_reply(choices=[{}])).encode(),
        json.dumps(example_reply(choices=[{"message": {"content": ""}}])).encode(),
        json.dumps(
            example_reply(choices=[{"message": {"content": "x" * 2001}}])
        ).encode(),
        json.dumps(
            example_reply(
                choices=[{"message": {"content": "safe", "tool_calls": [{}]}}]
            )
        ).encode(),
    ],
)
def test_malformed_or_unaccepted_response_is_rejected(body):
    adapter = transport_with(settings(), lambda _: httpx.Response(200, content=body))
    with pytest.raises(ProviderFailure) as raised:
        adapter.generate(request_for())
    assert raised.value.kind is FailureKind.RESPONSE


@pytest.mark.parametrize(
    "usage",
    [
        [],
        {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": False},
        USAGE_BODY | {"prompt_tokens": -1},
        USAGE_BODY | {"total_tokens": 21},
        USAGE_BODY | {"other": 8},
        USAGE_BODY | {"completion_tokens": "3"},
    ],
)
def test_invalid_reported_usage_is_unknown_and_rejected(usage):
    adapter = transport_with(
        settings(), lambda _: httpx.Response(200, json=example_reply(usage=usage))
    )
    with pytest.raises(ProviderFailure) as raised:
        adapter.generate(request_for())
    assert raised.value.kind is FailureKind.USAGE and raised.value.usage is None


def test_missing_usage_is_allowed_without_estimating_actual_tokens():
    wire = example_reply()
    del wire["usage"]
    reply = transport_with(
        settings(), lambda _: httpx.Response(200, json=wire)
    ).generate(request_for())
    assert reply.usage == {}


def test_transport_deadline_cancels_the_attempt_and_does_not_retry():
    calls, cancelled = [], []

    async def hang(req):
        calls.append(req)
        try:
            await asyncio.sleep(30)
        finally:
            cancelled.append(True)

    adapter = transport_with(settings(TWOWORLDS_AI_TIMEOUT_SECONDS="0.05"), hang)
    with pytest.raises(ProviderFailure) as raised:
        adapter.generate(request_for())
    assert raised.value.kind is FailureKind.TIMEOUT
    assert len(calls) == 1 and cancelled == [True]
    phases = calls[0].extensions["timeout"]
    assert set(phases) == {"connect", "read", "write", "pool"}
    assert all(0 < seconds <= 0.05 for seconds in phases.values())


def test_network_failure_and_input_limit_never_retry_or_expose_transport_error():
    calls = []

    def failed(req):
        calls.append(req)
        raise httpx.ReadError("PRIVATE_PROTOCOL_FAILURE", request=req)

    with pytest.raises(ProviderFailure, match="provider_transport_error"):
        transport_with(settings(), failed).generate(request_for())
    with pytest.raises(ProviderFailure, match="provider_input_limit"):
        transport_with(replace(settings(), max_input_tokens=10), failed).generate(
            request_for()
        )
    original = request_for()
    malformed = original.model_copy(
        update={"context": original.context.model_copy(update={"question": "\ud800"})}
    )
    adapter = transport_with(settings(), failed)
    assert not adapter.fits_input(malformed)
    with pytest.raises(ProviderFailure, match="provider_input_limit"):
        adapter.generate(malformed)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "variable,value",
    [
        ("MODE", "enabled"),
        ("PROVIDER", "unknown"),
        ("API_KEY", ""),
        ("BASE_URL", "http://gateway.test/v1"),
        ("BASE_URL", "https://secret@gateway.test/v1"),
        ("BASE_URL", "https://gateway.test/v1?SECRET=VALUE"),
        ("BASE_URL", "https://gateway.test/../v1"),
        ("BASE_URL", "https://gateway.test:foo/v1"),
        ("MODEL", ""),
        ("TIMEOUT_SECONDS", "NaN"),
        ("MAX_INPUT_TOKENS", "0"),
        ("MAX_REQUEST_COST_USD", "1"),
        ("INPUT_USD_PER_MILLION", ""),
        ("OUTPUT_USD_PER_MILLION", "-0.1"),
        ("PRICE_VERSION", ""),
    ],
)
def test_invalid_configuration_fails_closed_without_printing_details(variable, value):
    with pytest.raises(ProviderConfigError) as raised:
        settings(**{"TWOWORLDS_AI_" + variable: value})
    assert variable in str(raised.value)
    assert TEST_KEY not in str(raised.value) and "SECRET=VALUE" not in str(raised.value)


def test_demo_needs_no_key_and_http_allowed_only_for_explicit_loopback_test():
    assert load_provider_config({}) is None
    assert load_provider_config(TEST_ENV | {"TWOWORLDS_AI_MODE": "demo"}) is None
    local = TEST_ENV | {"TWOWORLDS_AI_BASE_URL": "http://127.0.0.1:8765/v1"}
    with pytest.raises(ProviderConfigError):
        load_provider_config(local)
    assert load_provider_config(local, allow_loopback_http=True).endpoint.endswith(
        "/chat/completions"
    )
    assert TEST_KEY not in repr(settings())


def test_total_deadline_stops_a_trickling_response_body():
    class SlowBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(20):
                await asyncio.sleep(0.015)
                yield b" "
            raise AssertionError("The deadline should cancel the read earlier")

    provider = transport_with(
        settings(TWOWORLDS_AI_TIMEOUT_SECONDS="0.05"),
        lambda _: httpx.Response(200, stream=SlowBody()),
    )
    with pytest.raises(ProviderFailure) as raised:
        provider.generate(request_for())
    assert raised.value.kind == FailureKind.TIMEOUT
