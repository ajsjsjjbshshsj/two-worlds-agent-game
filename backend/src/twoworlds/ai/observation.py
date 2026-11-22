"""Best-effort local NPC metrics, isolated from the command path."""

from contextlib import contextmanager
from contextvars import ContextVar
import logging
from queue import Full, Queue
from threading import Lock, Thread

from twoworlds.ports.narrative import PROMPT_VERSION

# Preserve the existing logging category and its ordinary level controls.
_logger = logging.getLogger("twoworlds.ai.graph")


class _LocalLog:
    def __init__(self, logger, capacity=64):
        self._logger = logger
        self._messages = Queue(maxsize=capacity)
        self._start_lock = Lock()
        self._started = False

    def offer(self, message):
        if not self._started:
            with self._start_lock:
                if not self._started:
                    Thread(
                        target=self._write, name="twoworlds-npc-metrics", daemon=True
                    ).start()
                    self._started = True
        try:
            self._messages.put_nowait(message)
        except Full:
            # A slow or blocked sink drops excess metrics instead of delaying play.
            pass

    def _write(self):
        while True:
            message = self._messages.get()
            try:
                self._logger.info(message)
            except Exception:
                # Avoid feeding raw sink errors back into any logger or command.
                pass


_local_log = _LocalLog(_logger)


def record_narrative(
    *,
    trace_id,
    provider_mode,
    provider_name,
    elapsed_ms,
    disposition,
    calls=0,
    fallback=False,
    error=None,
    usage=None,
    model=None,
    price_version=None,
    reserved_micros=None,
    charged_micros=None,
):
    """Queue only the named technical fields. The server invoice is unavailable."""
    try:
        if _logger.isEnabledFor(logging.INFO):
            reserved = reserved_micros if reserved_micros is not None else "unknown"
            settled = charged_micros if charged_micros is not None else "unknown"
            _local_log.offer(
                f"npc_workflow trace_id={trace_id} prompt_version={PROMPT_VERSION} "
                f"provider_mode={provider_mode} elapsed_ms={elapsed_ms} calls={calls} "
                f"fallback={fallback} error={error or 'none'} usage={usage or 'unknown'} "
                f"disposition={disposition} provider={provider_name} model={model} "
                f"price_version={price_version} reserved_usd_micros={reserved} "
                f"charged_usd_micros={settled} final_cost_usd_micros=unknown"
            )
    except Exception:
        # A disabled or unavailable local observer has no impact on the request.
        pass


_private_transport = ContextVar("npc_private_transport", default=False)


class _ProviderTransportFilter(logging.Filter):
    def filter(self, record):
        return not _private_transport.get()


_filter = _ProviderTransportFilter()
# HTTPX INFO logs include the URL and server-controlled reason phrase. The
# async HTTP core can also emit raw response headers and errors at DEBUG.
for _name in ("httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2"):
    logging.getLogger(_name).addFilter(_filter)


@contextmanager
def suppress_provider_transport_logs():
    token = _private_transport.set(True)
    try:
        yield
    finally:
        _private_transport.reset(token)
