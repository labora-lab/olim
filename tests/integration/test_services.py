"""Service-layer rules: parent-existence checks and the all-or-nothing batch.
These live in the services (not the repos), so they're tested at that seam."""

import pytest

from olim.api.exceptions import (
    AnnotationValidationError,
    DatasetNotFoundError,
    FieldNotFoundError,
    ItemNotFoundError,
    SchemeNotFoundError,
)
from olim.api.schemas.annotation import AnswerIn
from olim.api.schemas.scheme import SchemeCreateIn
from olim.api.services import (
    AnnotationService,
    DatasetService,
    ItemService,
    SchemeService,
)
from olim.dto import DatasetCreate
from olim.models import Annotation


class TestDatasetService:
    def test_create_then_get_round_trips(self, session):
        svc = DatasetService(session)
        created = svc.create(DatasetCreate(name="reviews"))
        assert svc.get(created.id).name == "reviews"

    def test_get_missing_raises_not_found(self, session):
        with pytest.raises(DatasetNotFoundError):
            DatasetService(session).get(999)


class TestItemService:
    def test_upload_creates_one_item_per_content(self, session, dataset):
        items = ItemService(session).upload(dataset.id, ["a", "b", "c"])
        assert [i.content for i in items] == ["a", "b", "c"]
        assert all(i.dataset_id == dataset.id for i in items)

    def test_upload_to_missing_dataset_raises(self, session):
        with pytest.raises(DatasetNotFoundError):
            ItemService(session).upload(999, ["a"])

    def test_list_only_returns_the_datasets_items(self, session, dataset):
        svc = ItemService(session)
        svc.upload(dataset.id, ["a", "b"])
        assert len(svc.list(dataset.id)) == 2


class TestSchemeService:
    def test_create_validates_dataset_exists(self, session):
        with pytest.raises(DatasetNotFoundError):
            SchemeService(session).create(999, SchemeCreateIn(name="x"))

    def test_create_returns_the_hydrated_tree(self, session, dataset):
        payload = SchemeCreateIn.model_validate({
            "name": "sentiment",
            "fields": [
                {
                    "type": "select",
                    "name": "sentiment",
                    "options": [{"name": "pos"}, {"name": "neg"}],
                }
            ],
        })
        scheme = SchemeService(session).create(dataset.id, payload)
        assert [o.name for o in scheme.fields[0].options] == ["pos", "neg"]

    def test_get_missing_raises(self, session):
        with pytest.raises(SchemeNotFoundError):
            SchemeService(session).get(999)


class TestAnnotationService:
    @pytest.fixture
    def numeric_field(self, make_field):
        return make_field("numeric", min=0, max=10, step=1)

    def test_valid_batch_is_saved(self, session, item, numeric_field):
        svc = AnnotationService(session)
        dtos = svc.set_answers(item.id, [AnswerIn(field_id=numeric_field.id, value=8)])
        assert [d.value for d in dtos] == [8.0]

    def test_annotating_missing_item_raises(self, session, numeric_field):
        with pytest.raises(ItemNotFoundError):
            AnnotationService(session).set_answers(
                999, [AnswerIn(field_id=numeric_field.id, value=1)]
            )

    def test_unknown_field_raises(self, session, item):
        with pytest.raises(FieldNotFoundError):
            AnnotationService(session).set_answers(
                item.id, [AnswerIn(field_id=999, value=1)]
            )

    def test_bad_batch_rejects_everything_and_saves_nothing(
        self, session, item, make_field
    ):
        good = make_field("numeric", min=0, max=10, step=1)
        bad = make_field("numeric", min=0, max=10, step=1)
        svc = AnnotationService(session)

        with pytest.raises(AnnotationValidationError) as exc:
            svc.set_answers(
                item.id,
                [
                    AnswerIn(field_id=good.id, value=5),  # valid
                    AnswerIn(field_id=bad.id, value=99),  # over max
                ],
            )

        # every error is reported, and nothing was written.
        assert set(exc.value.errors) == {bad.id}
        assert session.query(Annotation).count() == 0

    def test_source_defaults_to_human_and_can_be_overridden(
        self, session, item, numeric_field
    ):
        svc = AnnotationService(session)
        svc.set_answers(item.id, [AnswerIn(field_id=numeric_field.id, value=1)])
        svc.set_answers(
            item.id, [AnswerIn(field_id=numeric_field.id, value=2)], source="llm"
        )

        rows = session.query(Annotation).filter_by(field_id=numeric_field.id).all()
        assert {r.source: r.value for r in rows} == {"human": 1.0, "llm": 2.0}
