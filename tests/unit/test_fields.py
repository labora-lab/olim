"""
Unit tests for the field-kind domain (olim/fields).

Pure logic: parse() turns the client's raw `value` into a typed AnnotationValue,
validate() applies the field's rules. No database — Field/Option are built in
memory, since the kinds only read their attributes.
"""

import pytest

from olim.fields import FieldValidationError, kind_for
from olim.models import Field, Option


def make_field(type_, **config):
    """An unpersisted Field with the given config and named options."""
    option_names = config.pop("options", [])
    field = Field(id=1, scheme_id=1, name="f", type=type_, **config)
    field.options = [
        Option(id=i, field_id=1, name=n) for i, n in enumerate(option_names, start=1)
    ]
    return field


def annotate(field, raw):
    """parse + validate, the path the service runs per answer."""
    kind = kind_for(field.type)
    value = kind.parse(field, raw)
    kind.validate(field, value)
    return value


# --------------------------------------------------------------------------- #
# select
# --------------------------------------------------------------------------- #


class TestSelectKind:
    def test_single_option_id_parses_to_one_option(self):
        field = make_field("select", options=["a", "b", "c"])
        value = annotate(field, 2)
        assert value.option_ids == [2]

    def test_list_of_ids_parses_to_many_options_when_multi(self):
        field = make_field("select", multi=True, options=["a", "b", "c"])
        value = annotate(field, [1, 3])
        assert value.option_ids == [1, 3]

    def test_more_than_one_option_on_single_select_is_rejected(self):
        field = make_field("select", options=["a", "b"])
        with pytest.raises(FieldValidationError, match="only one option"):
            annotate(field, [1, 2])

    def test_unknown_option_id_is_rejected(self):
        field = make_field("select", options=["a", "b"])
        with pytest.raises(FieldValidationError, match="do not belong"):
            annotate(field, 99)

    def test_empty_list_is_rejected(self):
        field = make_field("select", multi=True, options=["a"])
        with pytest.raises(FieldValidationError, match="at least one option"):
            annotate(field, [])

    def test_free_text_rejected_without_allow_other(self):
        field = make_field("select", options=["a"])
        with pytest.raises(FieldValidationError, match="option id or list of ids"):
            annotate(field, "whatever")

    def test_free_text_accepted_with_allow_other(self):
        field = make_field("select", allow_other=True, options=["a"])
        value = annotate(field, "complaint")
        assert value.value_text == "complaint"
        assert value.option_ids is None

    def test_bool_is_not_a_valid_option_id(self):
        # bool is an int subclass; must not slip through as an option id.
        field = make_field("select", options=["a"])
        with pytest.raises(FieldValidationError, match="must be integers"):
            annotate(field, True)

    def test_allows_duplicate_only_when_multi(self):
        assert kind_for("select").allows_duplicate(make_field("select", multi=True))
        assert not kind_for("select").allows_duplicate(make_field("select"))


# --------------------------------------------------------------------------- #
# numeric
# --------------------------------------------------------------------------- #


class TestNumericKind:
    def test_int_and_float_parse_to_value_num(self):
        field = make_field("numeric")
        assert annotate(field, 8).value_num == pytest.approx(8.0)
        assert annotate(field, 3.5).value_num == pytest.approx(3.5)

    @pytest.mark.parametrize(
        ("raw", "message"),
        [
            pytest.param("high", "expected a number", id="string"),
            pytest.param(True, "expected a number", id="bool_is_not_a_number"),
        ],
    )
    def test_wrong_type_is_rejected(self, raw, message):
        field = make_field("numeric")
        with pytest.raises(FieldValidationError, match=message):
            annotate(field, raw)

    def test_value_below_min_is_rejected(self):
        field = make_field("numeric", min=0, max=10, step=1)
        with pytest.raises(FieldValidationError, match="below min"):
            annotate(field, -1)

    def test_value_above_max_is_rejected(self):
        field = make_field("numeric", min=0, max=10, step=1)
        with pytest.raises(FieldValidationError, match="above max 10"):
            annotate(field, 99)

    def test_off_grid_step_is_rejected(self):
        field = make_field("numeric", min=0, max=10, step=1)
        with pytest.raises(FieldValidationError, match="multiple of step"):
            annotate(field, 7.5)

    def test_on_grid_float_step_passes(self):
        # 0..1 step 0.1 — float arithmetic must not trip the tolerance.
        field = make_field("numeric", min=0, max=1, step=0.1)
        assert annotate(field, 0.3).value_num == pytest.approx(0.3)

    def test_unbounded_numeric_accepts_any_number(self):
        field = make_field("numeric")
        assert annotate(field, 1234.5).value_num == pytest.approx(1234.5)


# --------------------------------------------------------------------------- #
# text
# --------------------------------------------------------------------------- #


class TestTextKind:
    def test_string_parses_to_value_text(self):
        field = make_field("text")
        assert annotate(field, "a note").value_text == "a note"

    def test_non_string_is_rejected(self):
        field = make_field("text")
        with pytest.raises(FieldValidationError, match="expected a string"):
            annotate(field, 123)

    def test_empty_string_is_rejected(self):
        field = make_field("text")
        with pytest.raises(FieldValidationError, match="requires a value"):
            annotate(field, "")


# --------------------------------------------------------------------------- #
# boolean
# --------------------------------------------------------------------------- #


class TestBooleanKind:
    def test_true_and_false_parse_to_value_bool(self):
        field = make_field("boolean")
        assert annotate(field, True).value_bool is True
        assert annotate(field, False).value_bool is False

    def test_null_rejected_on_non_nullable(self):
        # parse() rejects None before validate() runs, so the message is the
        # parse one ("expected a boolean"), not validate's "requires a value".
        field = make_field("boolean")
        with pytest.raises(FieldValidationError, match="expected a boolean"):
            annotate(field, None)

    def test_null_accepted_on_nullable(self):
        field = make_field("boolean", nullable=True)
        value = annotate(field, None)
        assert value.value_bool is None

    def test_non_bool_is_rejected(self):
        field = make_field("boolean")
        with pytest.raises(FieldValidationError, match="expected a boolean"):
            annotate(field, "yes")
