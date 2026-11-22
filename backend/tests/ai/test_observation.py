"""Privacy and failure isolation for NPC metrics with no external services."""

from concurrent.futures import ThreadPoolExecutor
import json
import logging
import re
from threading import Event
from unittest.mock import Mock
from uuid import RFC_4122, UUID

import httpx
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.runnables import RunnableLambda
from langsmith import Client, tracing_context
from langsmith.utils import tracing_is_enabled
import pytest
import requests

from tests.ai import test_narrative_gateway as gateway
from tests.ai.log_support import wait_for_log
from tests.ai.test_graph import FakeProvider, fake_reply, request_for
from tests.ai.test_openai_compatible import TEST_KEY, example_reply, settings
from tests.contracts.support import error, ok
from tests.storage.conftest import (  # noqa: F401
    mongo_database,
    mongo_repository_factory,
    sqlite_repository_factory,
)
from twoworlds.ai import observation
from twoworlds.ai.graph import NarrativeLimits, NarrativeWorkflow
from twoworlds.application.dialogue import DEMO_ANSWER
from twoworlds.ports.narrative import PROMPT_VERSION

world = gateway.world
save_repository_factory = gateway.save_repository_factory
published_story = gateway.published_story

CATEGORY = "twoworlds.ai.graph"


@pytest.fixture
def capture_metrics(caplog):
    with caplog.at_level(logging.INFO, logger=CATEGORY):
        yield caplog


def metrics(caplog, expected):
    wait_for_log(caplog, expected)
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == CATEGORY and record.getMessage().startswith("npc_workflow ")
    ]


def test_default_demo_does_not_enqueue_metrics_or_call_provider(
    world, monkeypatch, caplog
):
    offer = Mock()
    monkeypatch.setattr(observation._local_log, "offer", offer)
    transport = Mock()
    game, repository = world(transport, demo=True)
    a, _, pair = game.pair()
    save = game.save(a, pair)
    with caplog.at_level(logging.WARNING, logger=CATEGORY):
        response = ok(game.post(a, save, gateway.talk(save)))
    assert response["save"]["personal"]["dialogue"][0]["mode"] == "demo"
    assert repository.get_save(save["id"]).version == 1
    assert repository.get_narrative_budget(gateway.day_id()) is None
    offer.assert_not_called()
    transport.assert_not_called()


def test_graph_blocks_env_tracing_and_inherited_runnable_callbacks(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.setenv("LANGSMITH_ENDPOINT", "https://trace.invalid")
    monkeypatch.setenv("LANGSMITH_API_KEY", "offline-synthetic-observer-key")
    network = Mock(side_effect=AssertionError("Tracing attempted network access"))
    create = Mock()
    update = Mock()
    monkeypatch.setattr(requests.Session, "request", network)
    monkeypatch.setattr(Client, "create_run", create)
    monkeypatch.setattr(Client, "update_run", update)

    def produce(request):
        assert not tracing_is_enabled()
        return fake_reply(request)

    provider = FakeProvider(produce)
    workflow = NarrativeWorkflow(provider, NarrativeLimits())
    starts = []

    class InheritedObserver(BaseCallbackHandler):
        def on_chain_start(self, serialized, inputs, **kwargs):
            starts.append(inputs)

    def invoke(_):
        with tracing_context(enabled=True):
            assert tracing_is_enabled()
            result = workflow.run(request_for("TRACE_PRIVATE_QUESTION"))
        return result.response.mode

    with tracing_context(enabled=False):
        outer = RunnableLambda(invoke).invoke(
            "synthetic outer operation", config={"callbacks": [InheritedObserver()]}
        )
    assert outer == "provider" and starts == ["synthetic outer operation"]
    assert len(provider.calls) == 1
    # Exercise the environment-only path, too, outside an explicit trace context.
    assert tracing_is_enabled()
    assert workflow.run(request_for()).response.mode == "provider"
    create.assert_not_called()
    update.assert_not_called()
    network.assert_not_called()


def test_metrics_have_only_technical_fields_and_confirmed_settlement(
    world, capture_metrics
):
    transport = Mock(return_value=httpx.Response(200, json=example_reply()))
    game, repo = world(transport)
    a, b, pair = game.pair()
    save = game.save(a, pair)
    save = game.accept(a, save, "talk", {"question": "PREVIOUS_PRIVATE_DIALOGUE"})
    save = game.accept(a, save, "inspect", {"target": "maintenance_log"})
    save = game.accept(b, save, "inspect", {"target": "sea_chart"})
    gateway.consent(game, a)
    command = gateway.talk(save, "CURRENT_PRIVATE_QUESTION")
    result = ok(game.post(a, save, command))
    assert result["save"]["personal"]["dialogue"][-1]["answer"] == "TEST_ONLY_NPC_REPLY"
    transport.assert_called_once()
    payload = json.loads(transport.call_args.args[0].content)
    assert "PREVIOUS_PRIVATE_DIALOGUE" in payload["messages"][1]["content"]
    record = metrics(capture_metrics, "charged_usd_micros=15")[-1]
    keys = set(re.findall(r"(?:^| )([a-z_]+)=", record))
    assert keys == {
        "trace_id",
        "prompt_version",
        "provider_mode",
        "elapsed_ms",
        "calls",
        "fallback",
        "error",
        "usage",
        "disposition",
        "provider",
        "model",
        "price_version",
        "reserved_usd_micros",
        "charged_usd_micros",
        "final_cost_usd_micros",
    }
    trace_ids = [
        UUID(re.search(r"trace_id=([a-f0-9]{32})", line)[1])
        for line in metrics(capture_metrics, "charged_usd_micros=15")
    ]
    assert len(set(trace_ids)) == len(trace_ids) == 2
    assert all(trace.version == 4 and trace.variant == RFC_4122 for trace in trace_ids)
    reserve = repo.get_narrative_budget(gateway.day_id()).reservations[-1]
    assert reserve.id not in trace_ids and UUID(command["request_id"]) not in trace_ids
    for field in (
        f"prompt_version={PROMPT_VERSION}",
        "provider_mode=provider",
        "provider=openai_compatible",
        "model=test-fixture-only",
        "calls=1",
        "fallback=False",
        "error=none",
        "disposition=committed",
        "price_version=test_prices_v1",
        f"reserved_usd_micros={reserve.reserved_micros}",
        "charged_usd_micros=15",
        "final_cost_usd_micros=unknown",
        "'input_tokens': 17",
        "'output_tokens': 3",
        "'total_tokens': 20",
    ):
        assert field in record
    assert reserve.charged_micros == 15
    for secret in (
        TEST_KEY,
        a.token,
        b.token,
        a.account_id,
        b.account_id,
        pair["id"],
        save["id"],
        command["request_id"],
        "CURRENT_PRIVATE_QUESTION",
        "PREVIOUS_PRIVATE_DIALOGUE",
        "TEST_ONLY_NPC_REPLY",
        "a_maintenance_log",
        "b_sea_chart",
        "emitter",
        "power_router",
        payload["messages"][0]["content"],
    ):
        assert secret not in record


@pytest.mark.parametrize(
    ("kind", "expected_error", "mode"),
    [
        ("no_usage", "none", "provider"),
        ("timeout", "provider_timeout", "fallback"),
        ("exception", "provider_error", "fallback"),
        ("http", "provider_unavailable_http", "fallback"),
    ],
)
def test_unknown_usage_and_cost_for_mock_failures(
    world, capture_metrics, kind, expected_error, mode
):
    def handle(_):
        if kind == "timeout":
            raise httpx.ReadTimeout("PRIVATE_PROVIDER_EXCEPTION")
        if kind == "exception":
            raise RuntimeError("PRIVATE_PROVIDER_EXCEPTION")
        if kind == "http":
            return httpx.Response(
                503,
                content=b"PRIVATE_PROVIDER_BODY",
                headers={"x-failure": "PRIVATE_PROVIDER_HEADER"},
                extensions={"reason_phrase": b"PRIVATE_PROVIDER_REASON"},
            )
        return httpx.Response(200, json=example_reply(usage=None))

    transport = Mock(side_effect=handle)
    game, repo = world(
        transport,
        settings(TWOWORLDS_AI_BASE_URL="https://gateway.test/PRIVATE_PROVIDER_ROUTE"),
    )
    a, _, pair = game.pair()
    save = game.save(a, pair)
    gateway.consent(game, a)
    with capture_metrics.at_level(logging.DEBUG):
        result = ok(game.post(a, save, gateway.talk(save)))
        records = metrics(capture_metrics, f"error={expected_error} usage=unknown")
        logging.getLogger("httpx").info("Unrelated local transport log")
    transport.assert_called_once()
    turn = result["save"]["personal"]["dialogue"][0]
    assert turn["mode"] == mode
    if mode == "fallback":
        assert turn["answer"] == DEMO_ANSWER
    reservation = repo.get_narrative_budget(gateway.day_id()).reservations[-1]
    assert reservation.charged_micros is None
    (record,) = records
    assert "calls=1" in record and f"fallback={mode == 'fallback'}" in record
    assert f"reserved_usd_micros={reservation.reserved_micros}" in record
    assert "charged_usd_micros=unknown final_cost_usd_micros=unknown" in record
    assert "disposition=committed" in record
    assert "PRIVATE_PROVIDER_" not in capture_metrics.text
    assert "Unrelated local transport log" in capture_metrics.text


def test_gateway_rejection_has_no_dispatch_charge_or_save_write(world, capture_metrics):
    transport = Mock()
    game, repo = world(transport, settings(TWOWORLDS_AI_MAX_INPUT_TOKENS="1"))
    a, _, pair = game.pair()
    save = game.save(a, pair)
    gateway.consent(game, a)
    before = repo.get_save(save["id"])
    command = gateway.talk(save)
    response = game.post(a, save, command)
    error(response, 422, "NARRATIVE_REQUEST_LIMIT")
    (record,) = metrics(capture_metrics, "disposition=gateway_rejected")
    assert "error=NARRATIVE_REQUEST_LIMIT usage=unknown" in record
    assert "reserved_usd_micros=unknown charged_usd_micros=unknown" in record
    assert "calls=0 fallback=False" in record
    transport.assert_not_called()
    assert repo.get_narrative_budget(gateway.day_id()) is None
    assert repo.get_save(save["id"]) == before
    assert game.receipt(a, save, command["request_id"]) == {"accepted": False}


class FakeObserver(logging.Handler):
    def __init__(self):
        super().__init__()
        self.entered = Event()
        self.unblock = Event()
        self.records = []

    def emit(self, record):
        self.records.append(record.getMessage())
        if len(self.records) == 1:
            self.entered.set()
            self.unblock.wait(15)
            raise RuntimeError("PRIVATE_OBSERVER_FAILURE")


def test_blocked_then_raising_observer_preserves_commit_and_stale_cas(
    world, capture_metrics, monkeypatch
):
    cas_waiting, cas_release = Event(), Event()
    requests_sent = []

    def handle(request):
        requests_sent.append(request)
        return httpx.Response(200, json=example_reply())

    game, repo = world(handle, settings(TWOWORLDS_AI_TIMEOUT_SECONDS="8"))
    peer, peer_repo = world(Mock())
    assert peer_repo is not repo
    a, b, pair = game.pair()
    save = game.save(a, pair)
    gateway.consent(game, a)
    before = repo.get_save(save["id"])
    first = gateway.talk(save, "FIRST_PRIVATE_QUESTION")
    fake = FakeObserver()
    logger = logging.getLogger(CATEGORY)
    logger.addHandler(fake)
    seen_writer_versions = []
    compare = repo.compare_and_swap_save

    def check_cas(save_id, version, candidate):
        if version == 1:
            # Pause after the final read so the competing write wins real CAS.
            cas_waiting.set()
            assert cas_release.wait(10)
        accepted = compare(save_id, version, candidate)
        seen_writer_versions.append((version, candidate.version, accepted))
        return accepted

    monkeypatch.setattr(repo, "compare_and_swap_save", check_cas)
    try:
        with ThreadPoolExecutor(1) as executor:
            try:
                pending = executor.submit(game.post, a, save, first)
                assert fake.entered.wait(5)
                first_result = ok(pending.result(timeout=3))
                assert not fake.unblock.is_set()
                advanced = first_result["save"]
                committed = repo.get_save(save["id"])
                assert committed.version == before.version + 1
                assert committed.dialogues[-1].answer == "TEST_ONLY_NPC_REPLY"
                assert committed.receipts[-1].request_id == UUID(first["request_id"])
                assert len(committed.dialogues) == len(committed.receipts) == 1
                repeated = ok(game.post(a, advanced, first))
                assert repeated["receipt"] == first_result["receipt"] | {
                    "duplicate": True
                }
                assert repeated["save"] == advanced and repeated["audio_events"] == []
                assert repo.get_save(save["id"]) == committed

                stale = gateway.talk(advanced, "STALE_PRIVATE_QUESTION")
                pending = executor.submit(game.post, a, advanced, stale)
                assert cas_waiting.wait(5)
                ahead = peer.accept(b, advanced, "inspect", {"target": "sea_chart"})
                assert ahead["version"] == 2
                cas_release.set()
                error(pending.result(timeout=5), 409, "VERSION_CONFLICT")
                assert not fake.unblock.is_set()
                final = repo.get_save(save["id"])
                assert (
                    final.version
                    == final.state.version
                    == final.public_history.through_version
                    == 2
                )
                assert final.dialogues == committed.dialogues
                assert (
                    len(final.receipts) == 2
                    and final.receipts[-1].actor_id == b.account_id
                )
                assert game.receipt(a, advanced, stale["request_id"]) == {
                    "accepted": False
                }
                assert seen_writer_versions == [
                    (0, 1, True),
                    (1, 2, False),
                ]
                assert len(requests_sent) == 2
            finally:
                cas_release.set()
                fake.unblock.set()
        records = metrics(capture_metrics, "disposition=stale")
        assert len(fake.records) == 2 and len(records) == 1
        assert "disposition=committed" in fake.records[0]
        assert "disposition=stale" in fake.records[1]
        assert "PRIVATE_OBSERVER_FAILURE" not in capture_metrics.text
        assert repo.get_save(save["id"]) == final and len(requests_sent) == 2
    finally:
        logger.removeHandler(fake)
