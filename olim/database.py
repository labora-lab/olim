from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from olim.config import DATABASE_URL

engine = create_engine(DATABASE_URL, echo=False)

SessionLocal = sessionmaker(engine)


@contextmanager
def worker_session() -> Iterator[Session]:
    """The session a Celery task runs in. A separate seam from the API's
    request session so tests (eager Celery) can override it to share the
    rolled-back test session instead of opening a real connection."""
    with SessionLocal() as session:
        yield session
