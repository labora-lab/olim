"""API fixtures: a TestClient whose DB session is the rolled-back test session,
so HTTP tests share the same isolation as the rest of the suite."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from olim.api.deps import get_session
from olim.api.main import app


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
