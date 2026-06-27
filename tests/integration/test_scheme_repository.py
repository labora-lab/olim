"""SchemeRepository.create_tree builds scheme+fields+options in one go;
reads hydrate the full tree back."""

import pytest

from olim.dto import SchemeCreate
from olim.dto.field import FieldSpec
from olim.repositories import SchemeRepository


@pytest.fixture
def repo(session):
    return SchemeRepository(session)


def make_tree(repo, dataset_id, name="form", fields=None):
    scheme_id = repo.create_tree(
        SchemeCreate(dataset_id=dataset_id, name=name), fields or []
    )
    return repo.get(scheme_id)


class TestCreateTree:
    def test_empty_scheme_hydrates_with_no_fields(self, repo, dataset):
        scheme = make_tree(repo, dataset.id, name="empty")
        assert scheme.name == "empty"
        assert scheme.fields == []

    def test_field_config_round_trips(self, repo, dataset):
        scheme = make_tree(
            repo,
            dataset.id,
            fields=[FieldSpec(name="score", type="numeric", min=0, max=10, step=1)],
        )
        field = scheme.fields[0]
        assert (field.name, field.type) == ("score", "numeric")
        assert (field.min, field.max, field.step) == (0, 10, 1)

    def test_select_field_keeps_its_options_in_order(self, repo, dataset):
        scheme = make_tree(
            repo,
            dataset.id,
            fields=[
                FieldSpec(
                    name="sentiment",
                    type="select",
                    options=["positive", "negative", "neutral"],
                )
            ],
        )
        names = [o.name for o in scheme.fields[0].options]
        assert names == ["positive", "negative", "neutral"]

    def test_multiple_fields_of_mixed_types(self, repo, dataset):
        scheme = make_tree(
            repo,
            dataset.id,
            fields=[
                FieldSpec(name="sentiment", type="select", options=["pos", "neg"]),
                FieldSpec(name="score", type="numeric", min=0, max=5, step=1),
                FieldSpec(name="notes", type="text"),
                FieldSpec(name="spam", type="boolean"),
            ],
        )
        assert [f.type for f in scheme.fields] == [
            "select",
            "numeric",
            "text",
            "boolean",
        ]

    def test_options_link_back_to_their_field(self, repo, dataset):
        scheme = make_tree(
            repo, dataset.id, fields=[FieldSpec(name="s", type="select", options=["a"])]
        )
        field = scheme.fields[0]
        assert scheme.fields[0].options[0].field_id == field.id


class TestListByDataset:
    def test_returns_every_scheme_as_a_full_tree(self, repo, dataset):
        make_tree(repo, dataset.id, name="a", fields=[FieldSpec(name="n", type="text")])
        make_tree(repo, dataset.id, name="b")

        schemes = repo.list_by_dataset(dataset.id)

        assert {s.name for s in schemes} == {"a", "b"}
        a = next(s for s in schemes if s.name == "a")
        assert a.fields[0].name == "n"  # tree hydrated on list, not just get

    def test_excludes_schemes_from_other_datasets(self, repo, session, dataset):
        from olim.models import Dataset

        other = Dataset(name="other")
        session.add(other)
        session.flush()
        make_tree(repo, dataset.id, name="mine")
        make_tree(repo, other.id, name="theirs")

        names = {s.name for s in repo.list_by_dataset(dataset.id)}
        assert names == {"mine"}
