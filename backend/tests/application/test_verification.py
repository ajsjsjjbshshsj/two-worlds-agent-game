from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import re
from threading import Barrier, Event

import pytest

from tests.identity_support import TEST_SECRET, FakeEmailSender, unique_email


@pytest.fixture(params=["sqlite", "mongo"])
def repository_factory(request):
    return request.getfixturevalue(f"{request.param}_repository_factory")


@pytest.fixture
def setup(repository_factory, now):
    from twoworlds.application.verification import VerificationCodeService

    repo = repository_factory()
    clock = [now]
    sender = FakeEmailSender()
    codes = iter(f"{n:06d}" for n in range(100000, 1000000))
    service = VerificationCodeService(
        repo,
        sender,
        secret=TEST_SECRET,
        clock=lambda: clock[0],
        code_generator=lambda: next(codes),
    )
    return service, repo, clock, sender


def test_request_and_consume_roundtrip(setup):
    from twoworlds.application.verification import VerificationError, code_id
    from twoworlds.security.credentials import verification_digest

    service, repo, clock, sender = setup
    email = unique_email()
    service.request_code(email, "register")
    code = sender.code_for(email, "register")
    assert re.fullmatch(r"[0-9]{6}", code)
    record = repo.get_verification_code(code_id(email, "register"))
    assert record.digest == verification_digest(TEST_SECRET, email, "register", code)
    assert code not in record.model_dump_json()
    assert record.expires_at == clock[0] + timedelta(minutes=10)
    assert record.attempts == 0 and record.consumed_at is None
    service.consume(email, "register", code)
    assert repo.get_verification_code(record.id).consumed_at == clock[0]
    # Single use: the same correct code cannot be consumed twice.
    with pytest.raises(VerificationError) as caught:
        service.consume(email, "register", code)
    assert caught.value.code == "INVALID_CODE"


def test_wrong_code_increments_attempts_and_locks_after_five(setup):
    from twoworlds.application.verification import VerificationError, code_id

    service, repo, _, sender = setup
    email = unique_email()
    service.request_code(email, "register")
    assert service.wait_for_delivery(10)
    code = sender.code_for(email, "register")
    identifier = code_id(email, "register")
    for attempt in range(1, 6):
        with pytest.raises(VerificationError) as caught:
            service.consume(email, "register", "000000")
        assert caught.value.code == "INVALID_CODE"
        assert repo.get_verification_code(identifier).attempts == attempt
    # Even the correct code is refused once the attempt budget is spent.
    with pytest.raises(VerificationError) as caught:
        service.consume(email, "register", code)
    assert caught.value.code == "CODE_LOCKED"
    assert repo.get_verification_code(identifier).attempts == 5


def test_expiry_boundary_and_cleanup_on_next_request(setup):
    from twoworlds.application.verification import VerificationError, code_id

    service, repo, clock, sender = setup
    email = unique_email()
    service.request_code(email, "register")
    assert service.wait_for_delivery(10)
    record = repo.get_verification_code(code_id(email, "register"))
    clock[0] = record.expires_at - timedelta(microseconds=1)
    service.consume(email, "register", sender.code_for(email, "register"))
    other = unique_email("other")
    service.request_code(other, "register")
    assert service.wait_for_delivery(10)
    identifier = code_id(other, "register")
    clock[0] = repo.get_verification_code(identifier).expires_at
    with pytest.raises(VerificationError) as caught:
        service.consume(other, "register", sender.code_for(other, "register"))
    assert caught.value.code == "CODE_EXPIRED"
    # The next request sweeps expired rows, including the one just refused.
    service.request_code(unique_email("third"), "register")
    assert service.wait_for_delivery(10)
    assert repo.get_verification_code(identifier) is None


def test_purpose_isolation(setup, account_factory):
    from twoworlds.application.verification import VerificationError, code_id

    service, repo, _, sender = setup
    account = account_factory()
    repo.create_account(account)
    email = account.email
    service.request_code(email, "register")
    service.request_code(email, "reset")
    assert service.wait_for_delivery(10)
    register_code = sender.code_for(email, "register")
    reset_code = sender.code_for(email, "reset")
    assert register_code != reset_code
    assert repo.get_verification_code(code_id(email, "register")) is not None
    assert repo.get_verification_code(code_id(email, "reset")) is not None
    for purpose, wrong in (("reset", register_code), ("register", reset_code)):
        with pytest.raises(VerificationError) as caught:
            service.consume(email, purpose, wrong)
        assert caught.value.code == "INVALID_CODE"
    service.consume(email, "register", register_code)
    service.consume(email, "reset", reset_code)


def test_resend_kills_old_code_and_resets_attempts(setup):
    from twoworlds.application.verification import VerificationError, code_id

    service, repo, _, sender = setup
    email = unique_email()
    service.request_code(email, "register")
    assert service.wait_for_delivery(10)
    old = sender.code_for(email, "register")
    with pytest.raises(VerificationError):
        service.consume(email, "register", "000000")
    service.request_code(email, "register")
    assert service.wait_for_delivery(10)
    new = sender.code_for(email, "register")
    assert new != old
    record = repo.get_verification_code(code_id(email, "register"))
    assert record.attempts == 0 and record.consumed_at is None
    with pytest.raises(VerificationError) as caught:
        service.consume(email, "register", old)
    assert caught.value.code == "INVALID_CODE"
    service.consume(email, "register", new)


def test_send_failure_invalidates_code_and_logs_safely(setup, caplog):
    from twoworlds.application.verification import VerificationError, code_id

    service, repo, _, sender = setup
    email = unique_email()
    sender.fail = True
    # Delivery is asynchronous: the request returns normally, then the failed
    # send invalidates its own code in the background.
    service.request_code(email, "register")
    assert service.wait_for_delivery(10)
    record = repo.get_verification_code(code_id(email, "register"))
    assert record.consumed_at is not None
    with pytest.raises(VerificationError) as caught:
        service.consume(email, "register", "123456")
    assert caught.value.code == "INVALID_CODE"
    assert email not in caplog.text
    assert "code=" not in caplog.text
    assert "delivery failed" in caplog.text
    sender.fail = False
    service.request_code(email, "register")
    assert service.wait_for_delivery(10)
    service.consume(email, "register", sender.code_for(email, "register"))


def test_reset_for_unknown_email_is_silent_but_records_like_known(setup):
    from twoworlds.application.verification import VerificationError, code_id

    service, repo, _, sender = setup
    email = unique_email()
    service.request_code(email, "reset")
    assert service.wait_for_delivery(10)
    # No mail leaves the server, but the stored path matches the known-address
    # path so the request timing stays uniform.
    assert all(sent_email != email for sent_email, _, _ in sender.sent)
    record = repo.get_verification_code(code_id(email, "reset"))
    assert record is not None and record.consumed_at is None
    with pytest.raises(VerificationError) as caught:
        service.consume(email, "reset", "123456")
    assert caught.value.code == "INVALID_CODE"


def test_failed_delivery_only_invalidates_its_own_issue(setup):
    from twoworlds.application.verification import (
        VerificationCodeService,
        VerificationError,
        code_id,
    )
    from twoworlds.ports.email import EmailSendError

    _, repo, clock, _ = setup
    email = unique_email()
    started, release = Event(), Event()

    class BlockingFirstSender(FakeEmailSender):
        def __init__(self):
            super().__init__()
            self.attempted = []

        def send_code(self, email, purpose, code):
            self.attempted.append(code)
            if len(self.attempted) == 1:
                started.set()
                assert release.wait(10)
                raise EmailSendError("first delivery fails")
            self.sent.append((email, purpose, code))

    sender = BlockingFirstSender()
    codes = iter(("300001", "300002"))
    service = VerificationCodeService(
        repo,
        sender,
        secret=TEST_SECRET,
        clock=lambda: clock[0],
        code_generator=lambda: next(codes),
    )
    service.request_code(email, "register")  # A: stored, send blocks
    assert started.wait(5)
    service.request_code(email, "register")  # B: replaces A, delivered
    release.set()
    assert service.wait_for_delivery(10)
    assert sender.attempted == ["300001", "300002"]
    record = repo.get_verification_code(code_id(email, "register"))
    assert record.consumed_at is None
    # A's failed send must not kill B's newer code.
    with pytest.raises(VerificationError) as caught:
        service.consume(email, "register", "300001")
    assert caught.value.code == "INVALID_CODE"
    service.consume(email, "register", "300002")


def test_register_code_issued_even_for_registered_email(setup, account_factory):
    service, repo, _, sender = setup
    account = account_factory()
    repo.create_account(account)
    # Enumeration parity: requesting a register code behaves the same whether
    # or not the email exists; the 409 only happens after a valid code.
    service.request_code(account.email, "register")
    assert service.wait_for_delivery(10)
    assert sender.code_for(account.email, "register")


def test_concurrent_consume_has_single_winner(setup, repository_factory):
    from twoworlds.application.verification import VerificationCodeService

    service, _, clock, sender = setup
    email = unique_email()
    service.request_code(email, "register")
    assert service.wait_for_delivery(10)
    code = sender.code_for(email, "register")
    barrier = Barrier(2)

    class FirstCASBarrier:
        def __init__(self, underlying):
            self.underlying = underlying
            self.first = True

        def __getattr__(self, name):
            return getattr(self.underlying, name)

        def compare_and_swap_verification_code(self, *args):
            if self.first:
                self.first = False
                barrier.wait(timeout=10)
            return self.underlying.compare_and_swap_verification_code(*args)

    services = [
        VerificationCodeService(
            FirstCASBarrier(repository_factory()),
            FakeEmailSender(),
            secret=TEST_SECRET,
            clock=lambda: clock[0],
        )
        for _ in range(2)
    ]

    def run(index):
        try:
            services[index].consume(email, "register", code)
            return "accepted"
        except Exception as exc:
            return exc.code

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(run, (0, 1)))
    assert sorted(results) == ["INVALID_CODE", "accepted"]


def test_concurrent_resend_keeps_one_live_code(setup, repository_factory):
    from twoworlds.application.verification import VerificationCodeService, code_id

    service, repo, clock, _ = setup
    email = unique_email()
    barrier = Barrier(2)

    class FirstWriteBarrier:
        def __init__(self, underlying):
            self.underlying = underlying
            self.first = True

        def __getattr__(self, name):
            return getattr(self.underlying, name)

        def _aligned(self, method, *args):
            if self.first:
                self.first = False
                barrier.wait(timeout=10)
            return method(*args)

        def create_verification_code(self, *args):
            return self._aligned(self.underlying.create_verification_code, *args)

        def compare_and_swap_verification_code(self, *args):
            return self._aligned(
                self.underlying.compare_and_swap_verification_code, *args
            )

    services, senders = [], []
    for index in range(2):
        sender = FakeEmailSender()
        senders.append(sender)
        fixed = f"{200000 + index:06d}"
        services.append(
            VerificationCodeService(
                FirstWriteBarrier(repository_factory()),
                sender,
                secret=TEST_SECRET,
                clock=lambda: clock[0],
                code_generator=lambda fixed=fixed: fixed,
            )
        )
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(lambda s: s.request_code(email, "register"), services))
    for candidate_service in services:
        assert candidate_service.wait_for_delivery(10)
    record = repo.get_verification_code(code_id(email, "register"))
    assert record.version == 1 and record.consumed_at is None
    codes = [sender.sent[0][2] for sender in senders]
    assert len(set(codes)) == 2
    outcomes = []
    for candidate in codes:
        try:
            service.consume(email, "register", candidate)
            outcomes.append("accepted")
        except Exception as exc:
            outcomes.append(exc.code)
    assert outcomes.count("accepted") == 1


@pytest.mark.parametrize(
    "email,purpose",
    [("not-an-email", "register"), ("player@example.com", "login"), ("a@b.co", None)],
)
def test_invalid_email_or_purpose(setup, email, purpose):
    from twoworlds.application.verification import VerificationError

    service, _, _, _ = setup
    for method, args in (
        (service.request_code, (email, purpose)),
        (service.consume, (email, purpose, "123456")),
    ):
        with pytest.raises(VerificationError) as caught:
            method(*args)
        assert caught.value.code == "INVALID_INPUT"


@pytest.mark.parametrize(
    "code", ["12345", "1234567", "abcdef", "12345a", None, 123456, "１２３４５６"]
)
def test_malformed_codes_are_refused_without_spending_attempts(setup, code):
    from twoworlds.application.verification import VerificationError, code_id

    service, repo, _, _ = setup
    email = unique_email()
    service.request_code(email, "register")
    assert service.wait_for_delivery(10)
    with pytest.raises(VerificationError) as caught:
        service.consume(email, "register", code)
    assert caught.value.code == "INVALID_CODE"
    assert repo.get_verification_code(code_id(email, "register")).attempts == 0


def test_constructor_rejects_weak_parameters(repository_factory, now):
    from twoworlds.application.verification import VerificationCodeService

    repo = repository_factory()
    sender = FakeEmailSender()
    for secret in ("short", 12345678901234567890123456789012, None):
        with pytest.raises(ValueError):
            VerificationCodeService(repo, sender, secret=secret)
    with pytest.raises(ValueError):
        VerificationCodeService(repo, sender, secret=TEST_SECRET, ttl=timedelta(0))
    with pytest.raises(ValueError):
        VerificationCodeService(repo, sender, secret=TEST_SECRET, max_verify_attempts=6)


def test_retry_exhaustion_and_dependency_errors(setup):
    from twoworlds.application.verification import (
        VerificationCodeService,
        VerificationError,
    )

    service, repo, clock, sender = setup
    email = unique_email()
    service.request_code(email, "register")
    assert service.wait_for_delivery(10)
    code = sender.code_for(email, "register")

    class NeverAccept:
        def __getattr__(self, name):
            return getattr(repo, name)

        def compare_and_swap_verification_code(self, *args):
            return False

    contested = VerificationCodeService(
        NeverAccept(),
        sender,
        secret=TEST_SECRET,
        clock=lambda: clock[0],
        max_attempts=3,
    )
    with pytest.raises(VerificationError) as caught:
        contested.consume(email, "register", code)
    assert caught.value.code == "CONCURRENT_UPDATE"
    with pytest.raises(VerificationError) as caught:
        contested.request_code(email, "register")
    assert caught.value.code == "CONCURRENT_UPDATE"
    repo.close()
    with pytest.raises(VerificationError) as caught:
        service.request_code(email, "register")
    assert caught.value.code == "DEPENDENCY_UNAVAILABLE"


def test_clock_rejection(setup):
    from twoworlds.application.verification import VerificationError

    service, _, clock, sender = setup
    email = unique_email()
    service.request_code(email, "register")
    assert service.wait_for_delivery(10)
    clock[0] -= timedelta(seconds=1)
    with pytest.raises(VerificationError) as caught:
        service.consume(email, "register", sender.code_for(email, "register"))
    assert caught.value.code == "CLOCK_ERROR"
    with pytest.raises(VerificationError) as caught:
        service.request_code(email, "register")
    assert caught.value.code == "CLOCK_ERROR"
