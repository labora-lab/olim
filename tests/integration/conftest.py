"""Integration fixtures: real rows in the rolled-back `session`."""

from collections.abc import Callable

import pytest
from sqlalchemy.orm import Session

from olim.models import Dataset, Field, Item, Option, Scheme


@pytest.fixture
def dataset(session: Session) -> Dataset:
    ds = Dataset(name="reviews")
    session.add(ds)
    session.flush()
    return ds


@pytest.fixture
def item(session: Session, dataset: Dataset) -> Item:
    it = Item(dataset_id=dataset.id, content="great battery life")
    session.add(it)
    session.flush()
    return it


@pytest.fixture
def make_field(session: Session, dataset: Dataset) -> Callable[..., Field]:
    """Create a Field (in its own one-field scheme) with named options."""

    def _make(type_: str, *, options: list[str] | None = None, **config) -> Field:
        scheme = Scheme(dataset_id=dataset.id, name=f"{type_} scheme")
        session.add(scheme)
        session.flush()
        field = Field(scheme_id=scheme.id, name=type_, type=type_, **config)
        session.add(field)
        session.flush()
        for name in options or []:
            session.add(Option(field_id=field.id, name=name))
        session.flush()
        return field

    return _make
