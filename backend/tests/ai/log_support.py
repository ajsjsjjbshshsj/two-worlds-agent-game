"""Wait for the asynchronous local metrics under pytest's log capture."""

from threading import Event
from time import monotonic


def wait_for_log(caplog, text):
    deadline = monotonic() + 5
    tick = Event()
    while text not in caplog.text and monotonic() < deadline:
        tick.wait(0.01)
    assert text in caplog.text
