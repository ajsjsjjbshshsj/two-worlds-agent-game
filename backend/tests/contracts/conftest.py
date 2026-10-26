from contextlib import ExitStack
from importlib import import_module
from importlib.util import find_spec

import pytest
from fastapi.testclient import TestClient

from .support import Platform

ORIGIN = "http://testserver"


@pytest.fixture
def client_factory(tmp_path):
    """Open real applications; separate instances can share one SQLite file."""
    with ExitStack() as stack:

        def open_client(database_path=None):
            # Delay application imports so collection works before T04/T08 exist.
            # Only known absent modules get this message; other import bugs stay errors.
            required = ("twoworlds.api.app", "twoworlds.storage.sqlite")
            missing = [name for name in required if find_spec(name) is None]
            if missing:
                pytest.fail(
                    "契约尚无业务实现（T04/T08）：" + ", ".join(missing),
                    pytrace=False,
                )
            create_app = import_module(required[0]).create_app
            repository = import_module(required[1]).SQLiteRepository(
                str(database_path or tmp_path / "contract.db")
            )
            app = create_app(
                repository=repository,
                ai_mode="demo",
                allowed_origins=[ORIGIN],
            )
            app_lifetime = stack.enter_context(ExitStack())
            client = app_lifetime.enter_context(TestClient(app))
            return Platform(client, app_lifetime.close)

        yield open_client
