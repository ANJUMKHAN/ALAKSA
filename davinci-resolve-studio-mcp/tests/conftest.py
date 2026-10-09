import os
import sys

FAKE = os.path.join(os.path.dirname(__file__), "fake_resolve")
sys.path.insert(0, FAKE)

import DaVinciResolveScript  # noqa: E402
import pytest  # noqa: E402

from davinci_resolve_mcp.client import session  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_resolve():
    DaVinciResolveScript._app = None
    session.set(DaVinciResolveScript.scriptapp("Resolve"))
    yield session.resolve()
