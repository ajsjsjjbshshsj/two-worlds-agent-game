"""Verification-code delivery adapters.

Console is for an explicitly selected local development mode only and writes to
the development console (stdout), never the application logger. SMTP reads all
configuration from the environment, enforces TLS and timeouts, and surfaces only
a sanitized EmailSendError. Neither adapter is a default fallback: the caller
must inject a sender deliberately.
"""

from collections.abc import Mapping
from email.message import EmailMessage
import smtplib
import ssl

from twoworlds.ports.email import EmailSendError


def _message(email: str, purpose: str, code: str, sender: str) -> EmailMessage:
    message = EmailMessage()
    message["From"] = sender
    message["To"] = email
    message["Subject"] = "TwoWorlds 邮箱验证码"
    label = "注册" if purpose == "register" else "找回密码"
    message.set_content(
        f"您正在{label} TwoWorlds 账号。\n验证码：{code}\n"
        "10 分钟内有效，单次使用，最多尝试 5 次。请勿向任何人泄露此验证码。"
    )
    return message


class ConsoleEmailCodeSender:
    """Explicit local development only; prints the code to the dev console."""

    def send_code(self, email: str, purpose: str, code: str) -> None:
        # stdout is the development console, not the application logging system.
        print(f"[dev-email] to={email} purpose={purpose} code={code}", flush=True)


class SmtpEmailCodeSender:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        sender: str,
        timeout: float = 10.0,
    ):
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._sender = sender
        self._timeout = timeout

    def send_code(self, email: str, purpose: str, code: str) -> None:
        message = _message(email, purpose, code, self._sender)
        try:
            if self._port == 465:
                server = smtplib.SMTP_SSL(
                    self._host,
                    self._port,
                    timeout=self._timeout,
                    context=ssl.create_default_context(),
                )
            else:
                server = smtplib.SMTP(self._host, self._port, timeout=self._timeout)
            try:
                server.ehlo()
                if self._port != 465:
                    server.starttls(context=ssl.create_default_context())
                    server.ehlo()
                if self._username:
                    server.login(self._username, self._password)
                server.send_message(message)
            finally:
                try:
                    server.quit()
                except Exception:
                    pass
        except Exception:
            # Never propagate upstream stacks, addresses, or credentials.
            raise EmailSendError("Verification email delivery failed") from None


def build_email_sender(env: Mapping[str, str]):
    mode = env.get("TWOWORLDS_EMAIL_MODE")
    if mode == "console":
        return ConsoleEmailCodeSender()
    if mode == "smtp":
        host = env.get("SMTP_HOST")
        username = env.get("SMTP_USERNAME")
        password = env.get("SMTP_PASSWORD")
        sender = env.get("SMTP_FROM")
        try:
            port = int(env.get("SMTP_PORT", "587"))
        except ValueError:
            raise ValueError("SMTP port must be an integer") from None
        if not host or not sender or not 1 <= port <= 65535:
            raise ValueError("Explicit SMTP host, port and from address required")
        if username and not password:
            raise ValueError("SMTP password required when username is set")
        return SmtpEmailCodeSender(
            host=host,
            port=port,
            username=username or "",
            password=password or "",
            sender=sender,
        )
    raise ValueError("Select an explicit email mode: console or smtp")
