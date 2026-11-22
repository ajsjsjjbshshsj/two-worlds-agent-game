"""Consent and billing boundaries surrounding the existing LangGraph workflow."""

from dataclasses import replace
from datetime import datetime, timezone
from time import monotonic
from uuid import UUID, uuid4

from twoworlds.ai.graph import NarrativeLimits, NarrativeWorkflow
from twoworlds.ai.observation import record_narrative
from twoworlds.ai.providers.config import ProviderConfig
from twoworlds.ai.providers.openai_compatible import OpenAICompatibleProvider
from twoworlds.domain.persistence import NarrativeBudgetRecord, NarrativeReservation
from twoworlds.ports.repository import RepositoryError


class GatewayRejected(RuntimeError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class NarrativeBudget:
    def __init__(self, repository, clock=lambda: datetime.now(timezone.utc)):
        self._repo = repository
        self._clock = clock

    def reserve(self, config: ProviderConfig, reservation_id: UUID | None = None):
        now = self._clock().astimezone(timezone.utc)
        day = now.strftime("ai_budget_%Y_%m_%d")
        item = NarrativeReservation(
            id=reservation_id or uuid4(),
            price_version=config.pricing.version,
            reserved_micros=config.reservation_micros,
        )
        if item.reserved_micros > config.max_request_micros:
            raise GatewayRejected("NARRATIVE_REQUEST_LIMIT")
        for _ in range(16):
            current = self._repo.get_narrative_budget(day)
            previous = current.reservations if current else ()
            if any(existing.id == item.id for existing in previous):
                raise GatewayRejected("NARRATIVE_IN_PROGRESS")
            committed = current.committed_micros if current else 0
            if (
                len(previous) >= config.max_daily_calls
                or committed + item.reserved_micros > config.daily_budget_micros
            ):
                raise GatewayRejected("NARRATIVE_BUDGET_EXCEEDED")
            candidate = NarrativeBudgetRecord(
                id=day,
                version=current.version + 1 if current else 0,
                reservations=(*previous, item),
            )
            if self._repo.compare_and_swap_narrative_budget(
                candidate, current.version if current else None
            ):
                return day, item
        raise RepositoryError("Narrative budget reservation contention")

    def finish(self, day, reservation: NarrativeReservation, charged: int | None):
        """Settle a known charge, or remove a reservation for a call never dispatched."""
        for _ in range(16):
            current = self._repo.get_narrative_budget(day)
            if current is None:
                raise RepositoryError("Narrative reservation missing")
            item = next(
                (r for r in current.reservations if r.id == reservation.id), None
            )
            if item is None or (
                item.charged_micros is not None and item.charged_micros != charged
            ):
                raise RepositoryError("Narrative reservation is not open")
            if item.charged_micros is not None:
                return
            revised = tuple(
                r
                if r.id != reservation.id
                else NarrativeReservation(
                    id=r.id,
                    price_version=r.price_version,
                    reserved_micros=r.reserved_micros,
                    charged_micros=charged,
                )
                for r in current.reservations
                if r.id != reservation.id or charged is not None
            )
            candidate = NarrativeBudgetRecord(
                id=day,
                version=current.version + 1,
                reservations=revised,
            )
            if self._repo.compare_and_swap_narrative_budget(candidate, current.version):
                return
        raise RepositoryError("Narrative budget settlement contention")


class NarrativeGateway:
    def __init__(
        self, repository, config, max_concurrent, *, transport=None, clock=None
    ):
        self.config = config
        self._budget = NarrativeBudget(
            repository, **({"clock": clock} if clock else {})
        )
        self._provider = OpenAICompatibleProvider(config, transport=transport)
        # Give the HTTP cancellation deadline time to complete inside LangGraph.
        self._workflow = NarrativeWorkflow(
            self._provider, NarrativeLimits(config.timeout + 0.25, max_concurrent)
        )

    def has_consent(self, account):
        return (
            account is not None and account.narrative_consent == self.config.disclosure
        )

    def run(self, request, reauthorize, reservation_id):
        if not self.has_consent(reauthorize()):
            return None
        start = monotonic()
        try:
            if not self._provider.fits_input(request):
                raise GatewayRejected("NARRATIVE_REQUEST_LIMIT")
            day, reservation = self._budget.reserve(self.config, reservation_id)
        except GatewayRejected as error:
            record_narrative(
                trace_id=uuid4().hex,
                provider_mode="provider",
                provider_name=self._provider.provider_name,
                model=self.config.model,
                price_version=self.config.pricing.version,
                elapsed_ms=round((monotonic() - start) * 1000),
                error=error.code,
                disposition="gateway_rejected",
            )
            raise

        # Recheck after the separate budget transaction, before any dispatch.
        try:
            consent = self.has_consent(reauthorize())
        except Exception:
            self._budget.finish(day, reservation, None)
            raise
        if not consent:
            self._budget.finish(day, reservation, None)
            return None

        run = replace(
            self._workflow.run(request),
            provider_name=self._provider.provider_name,
            model=self.config.model,
            price_version=self.config.pricing.version,
            reserved_micros=reservation.reserved_micros,
        )
        try:
            usage = run.metered_usage
            if usage is None:
                if run.error in {
                    "capacity",
                    "provider_unavailable",
                    "invalid_context",
                    "provider_input_limit",
                }:
                    self._budget.finish(day, reservation, None)
                return run
            charged = self.config.pricing.micros(
                usage["input_tokens"], usage["output_tokens"]
            )
            self._budget.finish(day, reservation, charged)
            run = replace(run, charged_micros=charged)
            if (
                usage["input_tokens"] > self.config.max_input_tokens
                or usage["output_tokens"] > self.config.max_output_tokens
                or charged > reservation.reserved_micros
            ):
                raise GatewayRejected("NARRATIVE_REQUEST_LIMIT")
            return run
        except RepositoryError:
            replace(run, error="billing_unavailable").record("billing_rejected")
            raise
        except GatewayRejected as error:
            replace(run, error=error.code).record("billing_rejected")
            raise
