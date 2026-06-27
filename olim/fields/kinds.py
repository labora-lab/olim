from typing import TYPE_CHECKING

from olim.fields.base import AnnotationValue, FieldKind, FieldValidationError

if TYPE_CHECKING:
    from olim.models import Field


def _only(value: AnnotationValue, *allowed: str) -> None:
    """Reject any value column set that is not in `allowed`."""
    for name in ("option_id", "value_num", "value_text", "value_bool"):
        if name not in allowed and getattr(value, name) is not None:
            raise FieldValidationError(f"this field does not accept {name}")


class SelectKind(FieldKind):
    def validate(self, field: Field, value: AnnotationValue) -> None:
        allowed = ("option_id", "value_text") if field.allow_other else ("option_id",)
        _only(value, *allowed)
        if value.option_id is None and value.value_text is None:
            raise FieldValidationError(
                "select requires an option"
                + (" or a free-text value" if field.allow_other else "")
            )
        if value.option_id is not None:
            valid = {o.id for o in field.options}
            if value.option_id not in valid:
                raise FieldValidationError("option does not belong to this field")

    def allows_duplicate(self, field: Field) -> bool:
        return field.multi


class NumericKind(FieldKind):
    def validate(self, field: Field, value: AnnotationValue) -> None:
        _only(value, "value_num")
        v = value.value_num
        if v is None:
            raise FieldValidationError("numeric field requires value_num")
        if field.min is not None and v < field.min:
            raise FieldValidationError(f"value below min {field.min}")
        if field.max is not None and v > field.max:
            raise FieldValidationError(f"value above max {field.max}")
        if field.step is not None and field.min is not None:
            steps = (v - field.min) / field.step
            if abs(steps - round(steps)) > 1e-9:
                raise FieldValidationError(f"value not a multiple of step {field.step}")


class TextKind(FieldKind):
    def validate(self, field: Field, value: AnnotationValue) -> None:  # noqa: ARG002
        _only(value, "value_text")
        if not value.value_text:
            raise FieldValidationError("text field requires value_text")


class BooleanKind(FieldKind):
    def validate(self, field: Field, value: AnnotationValue) -> None:
        _only(value, "value_bool")
        if value.value_bool is None and not field.nullable:
            raise FieldValidationError("boolean field requires value_bool")
