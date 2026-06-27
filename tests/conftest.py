"""
Shared test fixtures.

Integration tests run against a real Postgres so constraints/types match prod.
We never touch the dev database: a dedicated `<db>_test` database is created once
per session from the schema, and each test runs inside a transaction that is rolled
back on teardown — so tests may flush/commit freely and still stay isolated.

Needs `docker compose up -d db`. Override the target DB with TEST_DATABASE_URL.
"""

import os
from collections.abc import Iterator

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from olim.config import DATABASE_URL
from olim.models import Base


def pytest_collection_modifyitems(items):
    """Auto-mark by location: tests/unit -> unit, everything else -> integration
    (those use the `session` fixture and need a real Postgres)."""
    for item in items:
        marker = "unit" if "/unit/" in str(item.path) else "integration"
        item.add_marker(marker)


def _test_database_url() -> str:
    if url := os.getenv("TEST_DATABASE_URL"):
        return url
    # derive `<db>_test` from the dev URL so a bare `compose up -d db` is enough.
    base = sa.make_url(DATABASE_URL)
    return base.set(database=f"{base.database}_test").render_as_string(
        hide_password=False
    )


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    url = sa.make_url(_test_database_url())
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.execute(
            sa.text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": url.database}
        ).scalar()
        if not exists:
            conn.execute(sa.text(f'CREATE DATABASE "{url.database}"'))
    admin.dispose()

    engine = create_engine(url)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """A session wrapped in a transaction that is rolled back after the test.

    The nested-savepoint listener restarts the savepoint whenever the test
    commits, so application code under test can commit without leaking state.
    """
    conn = engine.connect()
    outer = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        outer.rollback()
        conn.close()
