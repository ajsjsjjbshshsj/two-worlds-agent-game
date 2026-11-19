"""Outbound verification-code delivery port. Adapters carry no game or identity rules."""

from typing import Protocol


class EmailSendError(RuntimeError):
    """Delivery failed. Callers invalidate the code and return a uniform response.

    The message must stay sanitized: no email plaintext, code, or SMTP credential.
    """


class EmailCodeSender(Protocol):
    def send_code(self, email: str, purpose: str, code: str) -> None:
        """Deliver a six-digit code for register/reset, or raise EmailSendError."""
        ...
