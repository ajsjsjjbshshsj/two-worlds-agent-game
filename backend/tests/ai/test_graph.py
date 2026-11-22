from concurrent.futures import ThreadPoolExecutor
import logging
from threading import Event, current_thread

from langsmith.utils import tracing_is_enabled
import pytest

from tests.ai.log_support import wait_for_log
from twoworlds.ai.graph import NarrativeLimits, NarrativeWorkflow
from twoworlds.application.dialogue import DEMO_ANSWER, DemoNarrativeProvider
from twoworlds.ports.narrative import (
    PROMPT_VERSION,
    NarrativeContext,
    NarrativeProvider,
    NarrativeRequest,
    NarrativeResponse,
)


class FakeProvider(NarrativeProvider):
    provider_name = "fake"
    mode = "provider"

    def __init__(self, output):
        self.output = output
        self.calls = []

    def generate(self, request):
        self.calls.append(request)
        return self.output(request)


def request_for(question="SENSITIVE_PLAYER_QUESTION", role="a"):
    return NarrativeRequest(
        context=NarrativeContext(
            script_id="lighthouse",
            script_version="1.0.0",
            scene_id="opening",
            role=role,
            personal_clues=(),
            shared_clues=(),
            personal_devices=(),
            public_milestones=(),
            recent_dialogue=(),
            question=question,
            persona={"name": "lighthouse", "bio": "Private narrative test persona"},
        ),
    )


def fake_reply(request, **overrides):
    return {
        "text": "PRIVATE_GENERATED_ANSWER",
        "provider_name": "fake",
        "mode": "provider",
        "prompt_version": request.prompt_version,
        **overrides,
    }


def test_compiled_topology_and_default_demo():
    flow = NarrativeWorkflow(DemoNarrativeProvider(), NarrativeLimits())
    edges = {(edge.source, edge.target) for edge in flow._graph.get_graph().edges}
    assert {
        ("__start__", "prepare"),
        ("prepare", "generate"),
        ("generate", "validate"),
        ("validate", "fallback"),
        ("validate", "__end__"),
        ("fallback", "__end__"),
    } <= edges
    assert flow._graph.checkpointer is None and flow._graph.cache is None
    run = flow.run(request_for())
    assert run.response == NarrativeResponse(
        text=DEMO_ANSWER,
        mode="demo",
        provider_name="demo",
        prompt_version=PROMPT_VERSION,
    )
    assert run.calls == 1 and not run.fallback and run.error is None


def test_fake_provider_validation_and_metadata_are_private(caplog, monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")

    def produce(request):
        assert not tracing_is_enabled()
        return fake_reply(request, usage={"input_tokens": 10, "output_tokens": 3})

    fake = FakeProvider(produce)
    flow = NarrativeWorkflow(fake, NarrativeLimits())
    with caplog.at_level(logging.INFO, logger="twoworlds.ai.graph"):
        first = flow.run(request_for("SECRET_1", "a"))
        second = flow.run(request_for("SECRET_2", "b"))
        first.record("committed")
        second.record("stale")
        wait_for_log(caplog, f"trace_id={second.trace_id}")
    assert [r.context.role for r in fake.calls] == ["a", "b"]
    assert [r.context.question for r in fake.calls] == ["SECRET_1", "SECRET_2"]
    assert first.trace_id != second.trace_id
    assert first.response.mode == second.response.mode == "provider"
    assert first.response.usage == {"input_tokens": 10, "output_tokens": 3}
    assert first.started_at <= first.finished_at and first.elapsed_ms >= 0
    assert "disposition=stale" in caplog.text and "calls=1" in caplog.text
    assert (
        "output_tokens" in caplog.text
        and f"prompt_version={PROMPT_VERSION}" in caplog.text
    )
    for secret in ("SECRET_1", "SECRET_2", "PRIVATE_GENERATED_ANSWER"):
        assert secret not in caplog.text


@pytest.mark.parametrize(
    "changes",
    [
        {"text": ""},
        {"text": " \n\t"},
        {"text": "x" * 2001},
        {"text": 41},
        {"text": "\ud800"},
        {"mode": "unsafe"},
        {"mode": "demo"},
        {"mode": "fallback"},
        {"provider_name": "BAD identifier"},
        {"provider_name": "another"},
        {"prompt_version": "9.9"},
        {"usage": []},
        {"usage": {"input_tokens": True}},
        {"usage": {"input_tokens": "1"}},
        {"usage": {"input_tokens": -1}},
        {"usage": {"secret": 5}},
        {"rule_updates": {"completed": True}},
        {"command": {"kind": "force_ending"}},
        {"authorized_role": "b"},
        {"error_code": "FAKE_SUCCESS"},
        {"timeout_ms": 20},
    ],
)
def test_invalid_output_uses_validated_fallback_without_retry(changes):
    fake = FakeProvider(lambda req: fake_reply(req, **changes))
    run = NarrativeWorkflow(fake, NarrativeLimits()).run(request_for())
    assert run.response.mode == "fallback"
    assert run.response.text == DEMO_ANSWER
    assert not run.response.usage
    assert run.error == "invalid_output" and run.fallback and run.calls == 1
    assert len(fake.calls) == 1
    assert "SENSITIVE_PLAYER_QUESTION" not in run.response.text


def test_already_constructed_response_is_revalidated():
    fake = FakeProvider(
        lambda req: NarrativeResponse.model_construct(**fake_reply(req, text=" "))
    )
    run = NarrativeWorkflow(fake, NarrativeLimits()).run(request_for())
    assert run.response.mode == "fallback" and run.error == "invalid_output"


def test_invalid_context_stops_before_provider():
    fake = FakeProvider(fake_reply)
    run = NarrativeWorkflow(fake, NarrativeLimits()).run(
        request_for().model_copy(update={"prompt_version": "0.0"})
    )
    assert run.response is None and run.error == "invalid_context"
    assert not run.fallback and run.calls == 0
    assert fake.calls == []


def test_exception_is_sanitized_and_usage_is_unknown(caplog):
    def crash(_):
        raise RuntimeError("SECRET_PROVIDER_EXCEPTION")

    fake = FakeProvider(crash)
    with caplog.at_level(logging.INFO, logger="twoworlds.ai.graph"):
        run = NarrativeWorkflow(fake, NarrativeLimits()).run(request_for())
        run.record("committed")
        wait_for_log(caplog, f"trace_id={run.trace_id}")
    assert run.response.text == DEMO_ANSWER and run.response.mode == "fallback"
    assert run.error == "provider_error" and run.calls == len(fake.calls) == 1
    assert "usage=unknown" in caplog.text
    assert "SECRET_PROVIDER_EXCEPTION" not in caplog.text


def test_timeout_keeps_slot_until_provider_really_finishes():
    entered, release, exited = Event(), Event(), Event()

    def hang(request):
        assert current_thread().daemon
        entered.set()
        try:
            if not release.wait(10):
                raise AssertionError("Test did not release the blocked provider")
            return fake_reply(request)
        finally:
            exited.set()

    fake = FakeProvider(hang)
    flow = NarrativeWorkflow(
        fake, NarrativeLimits(timeout_seconds=0.1, max_concurrent=1)
    )
    with ThreadPoolExecutor(1) as executor:
        try:
            pending = executor.submit(flow.run, request_for("A"))
            assert entered.wait(5)
            timed = pending.result(timeout=5)
            assert timed.response.mode == "fallback" and timed.error == "timeout"
            assert not exited.is_set()
            for _ in range(4):
                blocked = flow.run(request_for("B", "b"))
                assert (
                    blocked.response.mode == "fallback" and blocked.error == "capacity"
                )
                assert blocked.calls == 0 and blocked.fallback is True
            assert len(fake.calls) == 1
        finally:
            release.set()
        assert exited.wait(5)
    assert timed.response.text == DEMO_ANSWER


@pytest.mark.parametrize(
    "settings",
    [
        {"timeout_seconds": 0},
        {"timeout_seconds": float("nan")},
        {"timeout_seconds": 31},
        {"max_concurrent": True},
        {"max_concurrent": 17},
    ],
)
def test_limits_reject_invalid_settings(settings):
    with pytest.raises(ValueError, match="execution limits"):
        NarrativeLimits(**settings)
