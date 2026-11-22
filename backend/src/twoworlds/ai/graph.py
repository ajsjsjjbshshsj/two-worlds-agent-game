"""Request-local LangGraph workflow with bounded, non-queued provider calls."""

from concurrent.futures import Future, TimeoutError
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from math import isfinite
from threading import BoundedSemaphore, Thread
from time import monotonic
from typing import TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context
from pydantic import TypeAdapter

from twoworlds.ai.fallback import fallback_reply
from twoworlds.ai.providers.base import ProviderFailure
from twoworlds.ai.validation import validate_response
from twoworlds.content.schema import Identifier
from twoworlds.ports.narrative import (
    PROMPT_VERSION,
    NarrativeProvider,
    NarrativeRequest,
    NarrativeResponse,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NarrativeLimits:
    timeout_seconds: float = 2.0
    max_concurrent: int = 4

    def __post_init__(self):
        if (
            type(self.timeout_seconds) not in (int, float)
            or not isfinite(self.timeout_seconds)
            or not 0 < self.timeout_seconds <= 30
            or type(self.max_concurrent) is not int
            or not 1 <= self.max_concurrent <= 16
        ):
            raise ValueError("Invalid narrative execution limits")


class _Input(TypedDict):
    request: NarrativeRequest


class _Output(TypedDict, total=False):
    response: NarrativeResponse | None
    error: str | None
    fallback: bool
    calls: int
    metered_usage: dict[str, int] | None


class _State(_Input, _Output, total=False):
    raw: object


@dataclass(frozen=True)
class NarrativeRun:
    response: NarrativeResponse | None
    trace_id: str
    started_at: datetime
    finished_at: datetime
    elapsed_ms: int
    provider_mode: str
    calls: int
    fallback: bool
    error: str | None
    metered_usage: dict[str, int] | None = None
    provider_name: str | None = None
    model: str | None = None
    price_version: str | None = None
    reserved_micros: int | None = None
    charged_micros: int | None = None

    def record(self, disposition: str):
        # Allowlist only metadata. The provider exception, state and reply are
        # intentionally never passed to logging, even when validation fails.
        try:
            logger.info(
                "npc_workflow trace_id=%s prompt_version=%s provider_mode=%s "
                "started_at=%s finished_at=%s elapsed_ms=%d calls=%d fallback=%s "
                "error=%s usage=%s disposition=%s provider=%s model=%s price_version=%s reserved_usd_micros=%s charged_usd_micros=%s",
                self.trace_id,
                PROMPT_VERSION,
                self.provider_mode,
                self.started_at.isoformat(),
                self.finished_at.isoformat(),
                self.elapsed_ms,
                self.calls,
                self.fallback,
                self.error or "none",
                self.metered_usage or "unknown",
                disposition,
                self.provider_name,
                self.model,
                self.price_version,
                self.reserved_micros,
                self.charged_micros,
            )
        except Exception:
            # Observability can never change a command's outcome.
            pass


class NarrativeWorkflow:
    def __init__(self, provider: NarrativeProvider, limits: NarrativeLimits):
        self._provider = provider
        self._mode = provider.mode
        if self._mode not in ("demo", "provider"):
            raise ValueError("Invalid narrative provider mode")
        self._name = TypeAdapter(Identifier).validate_python(provider.provider_name)
        self._timeout = limits.timeout_seconds
        self._slots = BoundedSemaphore(limits.max_concurrent)

        graph = StateGraph(_State, input_schema=_Input, output_schema=_Output)
        graph.add_node("prepare", self._prepare)
        graph.add_node("generate", self._generate)
        graph.add_node("validate", self._validate)
        graph.add_node("fallback", self._fallback)
        graph.add_edge(START, "prepare")
        graph.add_conditional_edges(
            "prepare",
            lambda state: "stop" if state["error"] else "generate",
            {"stop": END, "generate": "generate"},
        )
        graph.add_edge("generate", "validate")
        graph.add_conditional_edges(
            "validate",
            lambda state: "done" if state["response"] is not None else "fallback",
            {"done": END, "fallback": "fallback"},
        )
        graph.add_edge("fallback", END)
        self._graph = graph.compile()

    @staticmethod
    def _prepare(state: _State):
        try:
            incoming = state["request"]
            request = NarrativeRequest.model_validate(
                incoming.model_dump(warnings=False), strict=True
            )
            if request.prompt_version != PROMPT_VERSION:
                return {"error": "invalid_context"}
        except (AttributeError, TypeError, ValueError):
            return {"error": "invalid_context"}
        return {"request": request, "error": None}

    def _generate(self, state: _State):
        if not self._slots.acquire(blocking=False):
            return {"calls": 0, "error": "capacity"}
        request = state["request"]
        future: Future[tuple[object, str | None, dict[str, int] | None]] = Future()

        def run():
            # This thread can outlive the request. It holds one slot until it
            # actually exits and has no route back into the graph or repository.
            try:
                with tracing_context(enabled=False):
                    result = self._provider.generate(request), None, None
            except ProviderFailure as error:
                result = (
                    None,
                    error.kind.value,
                    error.usage.as_dict() if error.usage else None,
                )
            except BaseException:
                result = None, "provider_error", None
            finally:
                self._slots.release()
            future.set_result(result)

        try:
            Thread(target=run, name="twoworlds-narrative", daemon=True).start()
        except RuntimeError:
            self._slots.release()
            return {"calls": 0, "error": "provider_unavailable"}
        try:
            raw, error, usage = future.result(timeout=self._timeout)
        except TimeoutError:
            return {"calls": 1, "error": "timeout"}
        return {"raw": raw, "calls": 1, "error": error, "metered_usage": usage}

    def _validate(self, state: _State):
        if state["error"]:
            return {"response": None}
        response = validate_response(
            state["raw"], state["request"], mode=self._mode, provider_name=self._name
        )
        return {
            "response": response,
            "error": None if response else "invalid_output",
            "raw": None,
            "metered_usage": response.usage if response and response.usage else None,
        }

    @staticmethod
    def _fallback(state: _State):
        request = state["request"]
        try:
            response = validate_response(
                fallback_reply(request), request, mode="fallback", provider_name="demo"
            )
        except Exception:
            response = None
        return {
            "response": response,
            "fallback": True,
            "error": state["error"] if response else "fallback_failed",
        }

    def run(self, request: NarrativeRequest) -> NarrativeRun:
        trace_id = uuid4().hex
        started_at = datetime.now(timezone.utc)
        start = monotonic()
        # Disable automatic external LangGraph/LangSmith tracing even if the
        # enclosing process has tracing environment variables or an active context.
        try:
            with tracing_context(enabled=False):
                output = self._graph.invoke({"request": request}) or {}
        except Exception:
            # Unexpected graph/runtime failures also leave the save untouched.
            output = {"error": "graph_unavailable"}
        return NarrativeRun(
            response=output.get("response"),
            trace_id=trace_id,
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
            elapsed_ms=round((monotonic() - start) * 1000),
            provider_mode=self._mode,
            calls=output.get("calls", 0),
            fallback=output.get("fallback", False),
            error=output.get("error"),
            metered_usage=output.get("metered_usage"),
            provider_name=self._name,
        )
