"""AnnotationRepository.set_answers: upsert per (item, field, source), with
multi-select fanning out to one row per option and reconciling on re-send."""

import pytest

from olim.fields import AnnotationValue
from olim.models import Annotation
from olim.repositories import AnnotationRepository


@pytest.fixture
def repo(session):
    return AnnotationRepository(session)


def values_for(session, item_id, field_id):
    rows = session.query(Annotation).filter_by(item_id=item_id, field_id=field_id).all()
    return sorted(r.value for r in rows)


class TestSetAnswers:
    def test_single_select_saves_one_row(self, repo, item, make_field):
        field = make_field("select", options=["a", "b"])
        oid = field.options[0].id

        dtos = repo.set_answers(
            item.id, "human", [(field, AnnotationValue(option_ids=[oid]))]
        )

        assert [d.value for d in dtos] == [oid]

    def test_re_annotating_replaces_the_prior_answer(
        self, repo, session, item, make_field
    ):
        field = make_field("select", options=["a", "b"])
        first, second = field.options[0].id, field.options[1].id

        repo.set_answers(
            item.id, "human", [(field, AnnotationValue(option_ids=[first]))]
        )
        repo.set_answers(
            item.id, "human", [(field, AnnotationValue(option_ids=[second]))]
        )

        assert values_for(session, item.id, field.id) == [second]

    def test_multi_select_fans_out_to_one_row_per_option(
        self, repo, session, item, make_field
    ):
        field = make_field("select", multi=True, options=["x", "y", "z"])
        ids = [o.id for o in field.options]

        repo.set_answers(item.id, "human", [(field, AnnotationValue(option_ids=ids))])

        assert values_for(session, item.id, field.id) == sorted(ids)

    def test_multi_select_reconciles_the_full_set(
        self, repo, session, item, make_field
    ):
        field = make_field("select", multi=True, options=["x", "y", "z"])
        x, y, z = (o.id for o in field.options)

        repo.set_answers(
            item.id, "human", [(field, AnnotationValue(option_ids=[x, y, z]))]
        )
        # re-send a smaller set: the others must be removed.
        repo.set_answers(item.id, "human", [(field, AnnotationValue(option_ids=[x]))])

        assert values_for(session, item.id, field.id) == [x]

    def test_allow_other_keeps_options_and_free_text(
        self, repo, session, item, make_field
    ):
        field = make_field("select", multi=True, allow_other=True, options=["a"])
        oid = field.options[0].id

        repo.set_answers(
            item.id,
            "human",
            [(field, AnnotationValue(option_ids=[oid], value_text="custom"))],
        )

        rows = session.query(Annotation).filter_by(field_id=field.id).all()
        assert {r.value for r in rows} == {oid, "custom"}

    def test_numeric_text_boolean_each_save_their_typed_value(
        self, repo, item, make_field
    ):
        num = make_field("numeric")
        txt = make_field("text")
        boo = make_field("boolean")

        dtos = repo.set_answers(
            item.id,
            "human",
            [
                (num, AnnotationValue(value_num=8.0)),
                (txt, AnnotationValue(value_text="note")),
                (boo, AnnotationValue(value_bool=False)),
            ],
        )

        assert {d.field_id: d.value for d in dtos} == {
            num.id: 8.0,
            txt.id: "note",
            boo.id: False,
        }

    def test_nullable_boolean_saves_a_null_row(self, repo, session, item, make_field):
        field = make_field("boolean", nullable=True)

        dtos = repo.set_answers(item.id, "human", [(field, AnnotationValue())])

        assert [d.value for d in dtos] == [None]
        rows = session.query(Annotation).filter_by(field_id=field.id).all()
        assert len(rows) == 1  # a real row, value None

    def test_different_sources_do_not_collide(self, repo, session, item, make_field):
        field = make_field("numeric")

        repo.set_answers(item.id, "human", [(field, AnnotationValue(value_num=1.0))])
        repo.set_answers(item.id, "llm", [(field, AnnotationValue(value_num=2.0))])

        # both survive: the upsert is scoped per source.
        rows = session.query(Annotation).filter_by(field_id=field.id).all()
        assert {r.source: r.value for r in rows} == {"human": 1.0, "llm": 2.0}

    def test_answers_to_other_fields_are_untouched(
        self, repo, session, item, make_field
    ):
        keep = make_field("numeric")
        change = make_field("numeric")
        repo.set_answers(item.id, "human", [(keep, AnnotationValue(value_num=5.0))])

        repo.set_answers(item.id, "human", [(change, AnnotationValue(value_num=9.0))])

        assert values_for(session, item.id, keep.id) == [5.0]
