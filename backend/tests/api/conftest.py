from contextlib import ExitStack
from datetime import datetime, timezone

from fastapi.testclient import TestClient
import pytest

from tests.identity_support import RELAXED_POLICIES, TEST_SECRET, FakeEmailSender
from tests.storage.conftest import mongo_database, mongo_repository_factory  # noqa: F401
from tests.save_support import published_story  # noqa: F401


@pytest.fixture
def clients(tmp_path):
    from twoworlds.api.app import create_app
    from twoworlds.storage.sqlite import SQLiteRepository

    with ExitStack() as stack:

        def factory(*, path=None, **options):
            repo = SQLiteRepository(path or tmp_path / "identity.sqlite")
            options.setdefault("email_sender", FakeEmailSender())
            options.setdefault("verification_secret", TEST_SECRET)
            options.setdefault("rate_policies", RELAXED_POLICIES)
            app = create_app(
                repository=repo,
                ai_mode="demo",
                allowed_origins=["http://testserver"],
                **options,
            )
            client = stack.enter_context(TestClient(app))
            return client, app, repo

        yield factory


@pytest.fixture
def clocks():
    return [datetime(2026, 11, 14, tzinfo=timezone.utc)], [0.0]
