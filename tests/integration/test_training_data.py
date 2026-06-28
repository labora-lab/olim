"""load_training_data builds the row-aligned DataBundle from a labeled dataset.
Hits Postgres (the rolled-back session), so it's an integration test."""

import pytest
from sqlalchemy.orm import Session

from olim.models import Annotation, Dataset, Field, Item, Option, Scheme
from olim.pipelines.data import (
    NoTargetFieldError,
    NotEnoughLabelsError,
    load_training_data,
)


def _labeled_dataset(session: Session, *, single_class: bool = False):
    """A dataset + scheme(select field pos/neg) + 4 items, 3 of them labeled
    (one item left unlabeled to prove it's dropped)."""
    ds = Dataset(name="reviews")
    session.add(ds)
    session.flush()

    scheme = Scheme(dataset_id=ds.id, name="sentiment")
    session.add(scheme)
    session.flush()
    field = Field(scheme_id=scheme.id, name="sentiment", type="select")
    session.add(field)
    session.flush()
    pos = Option(field_id=field.id, name="pos")
    neg = Option(field_id=field.id, name="neg")
    session.add_all([pos, neg])
    session.flush()

    items = [Item(dataset_id=ds.id, content=f"text {i}") for i in range(4)]
    session.add_all(items)
    session.flush()

    # items 0,1,2 labeled; item 3 left unlabeled. single_class -> all pos.
    labels = [pos, pos, pos] if single_class else [pos, neg, pos]
    for it, opt in zip(items[:3], labels, strict=True):
        session.add(Annotation(item_id=it.id, field_id=field.id, option_id=opt.id))
    session.flush()
    return ds, scheme, items, (pos, neg)


def test_bundle_is_row_aligned_and_drops_unlabeled(session):
    ds, scheme, items, (pos, neg) = _labeled_dataset(session)
    bundle = load_training_data(session, ds.id, scheme.id)

    assert bundle.item_ids == [it.id for it in items[:3]]  # item 3 dropped
    assert bundle.texts == ["text 0", "text 1", "text 2"]
    assert bundle.classes == sorted([pos.id, neg.id])
    # labels are class indices into `classes`, row-aligned to texts/item_ids
    expected = [bundle.classes.index(o.id) for o in (pos, neg, pos)]
    assert bundle.labels == expected


def test_llm_label_does_not_shadow_human_label(session):
    # item 1 is human-labeled neg; add a contradicting llm pos on it. Training
    # must keep the human neg, regardless of row order.
    ds, scheme, items, (pos, neg) = _labeled_dataset(session)
    target = next(f for f in scheme.fields if f.type == "select")
    session.add(
        Annotation(
            item_id=items[1].id, field_id=target.id, option_id=pos.id, source="llm"
        )
    )
    session.flush()

    bundle = load_training_data(session, ds.id, scheme.id)
    row = bundle.item_ids.index(items[1].id)
    assert bundle.labels[row] == bundle.classes.index(neg.id)


def test_no_select_field_raises(session):
    ds = Dataset(name="d")
    session.add(ds)
    session.flush()
    scheme = Scheme(dataset_id=ds.id, name="s")
    session.add(scheme)
    session.flush()
    session.add(Field(scheme_id=scheme.id, name="note", type="text"))
    session.flush()
    with pytest.raises(NoTargetFieldError):
        load_training_data(session, ds.id, scheme.id)


def test_single_class_raises(session):
    ds, scheme, *_ = _labeled_dataset(session, single_class=True)
    with pytest.raises(NotEnoughLabelsError):
        load_training_data(session, ds.id, scheme.id)
