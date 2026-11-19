"""Shared email-auth vocabulary for HTTP tests: fake sender, cookies, origins."""

from threading import Event
from uuid import uuid4

from twoworlds.application.rate_limit import RateLimitPolicy
from twoworlds.ports.email import EmailSendError

ORIGIN = "http://testserver"
ORIGIN_HEADER = {"Origin": ORIGIN}
PASSWORD = "correct horse 9"
TEST_SECRET = "test-verification-secret-0123456789abcdef"
RELAXED_POLICIES = {
    name: RateLimitPolicy(10000, 60)
    for name in (
        "code_email_minute",
        "code_email_hour",
        "code_ip_hour",
        "login_minute",
        "login_hour",
        "login_ip_minute",
        "login_ip_hour",
    )
}


class FakeEmailSender:
    """Controllable test double; never touches a real mailbox.

    Pass a gate to hold every send until the test releases it, which proves
    the HTTP response no longer waits for delivery.
    """

    def __init__(self, *, fail=False, gate: Event | None = None):
        self.sent = []
        self.fail = fail
        self.gate = gate

    def send_code(self, email, purpose, code):
        if self.gate is not None:
            self.gate.wait(timeout=10)
        if self.fail:
            raise EmailSendError("test delivery failure")
        self.sent.append((email, purpose, code))

    def code_for(self, email, purpose):
        for sent_email, sent_purpose, code in reversed(self.sent):
            if sent_email == email and sent_purpose == purpose:
                return code
        raise AssertionError(f"No {purpose} code sent to {email}")


def unique_email(prefix="player"):
    return f"{prefix}-{uuid4().hex[:12]}@example.com"


def request_code(client, email, purpose="register"):
    response = client.post(
        "/api/verification-codes",
        json={"email": email, "purpose": purpose},
        headers=ORIGIN_HEADER,
    )
    assert response.status_code == 202, response.text
    # Delivery is asynchronous by design; tests that need the code wait here.
    # Peer wrappers expose an ASGI function instead of the FastAPI app, so the
    # wait is best-effort there (the owning client drains on shutdown).
    state = getattr(client.app, "state", None)
    if state is not None and hasattr(state, "verification_service"):
        assert state.verification_service.wait_for_delivery(10)
    return response


def register(client, email=None, name="玩家", password=PASSWORD):
    """Full register flow; returns the body plus the cookie token for headers."""
    email = email or unique_email()
    sender = client.app.state.email_sender
    request_code(client, email)
    response = client.post(
        "/api/accounts",
        json={
            "email": email,
            "code": sender.code_for(email, "register"),
            "password": password,
            "display_name": name,
        },
        headers=ORIGIN_HEADER,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    token = response.cookies.get("tw_session")
    assert token
    return body | {"token": token, "password": password}


def login(client, who):
    response = client.post(
        "/api/sessions",
        json={"email": who["account"]["email"], "password": who["password"]},
        headers=ORIGIN_HEADER,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    token = response.cookies.get("tw_session")
    assert token
    return body | {"token": token, "password": who["password"]}


def auth(who):
    # Explicit Cookie header overrides the client jar, so one TestClient can
    # act as several identities request by request.
    return {"Cookie": f"tw_session={who['token']}", "Origin": ORIGIN}
