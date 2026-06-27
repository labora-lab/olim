from typing import TYPE_CHECKING

from olim.fields.base import AnnotationValue, FieldKind, FieldValidationError

if TYPE_CHECKING:
    from olim.models import Field

_ALL = ("option_ids", "value_num", "value_text", "value_bool")


def _only(value: AnnotationValue, *allowed: str) -> None:
    """Reject any value attribute set that is not in `allowed`."""
    for name in _ALL:
        if name not in allowed and getattr(value, name) is not None:
            raise FieldValidationError(f"this field does not accept {name}")


class SelectKind(FieldKind):
    def parse(self, field: Field, raw: object) -> AnnotationValue:
        # int -> one option; list[int] -> many; str -> free text (allow_other).
        if isinstance(raw, str):
            if not field.allow_other:
                raise FieldValidationError("expected an option id or list of ids")
            return AnnotationValue(value_text=raw)
        raws = raw if isinstance(raw, list) else [raw]
        ids: list[int] = []
        for i in raws:
            if not isinstance(i, int) or isinstance(i, bool):
                raise FieldValidationError("option ids must be integers")
            ids.append(i)
        return AnnotationValue(option_ids=ids)

    def validate(self, field: Field, value: AnnotationValue) -> None:
        allowed = ("option_ids", "value_text") if field.allow_other else ("option_ids",)
        _only(value, *allowed)

        ids = value.option_ids or []
        if not ids and not value.value_text:
            raise FieldValidationError(
                "select requires at least one option"
                + (" or a free-text value" if field.allow_other else "")
            )
        if not field.multi and len(ids) > 1:
            raise FieldValidationError("this select accepts only one option")

        valid = {o.id for o in field.options}
        unknown = [i for i in ids if i not in valid]
        if unknown:
            raise FieldValidationError(
                f"options do not belong to this field: {unknown}"
            )

    def allows_duplicate(self, field: Field) -> bool:
        return field.multi


class NumericKind(FieldKind):
    def parse(self, field: Field, raw: object) -> AnnotationValue:  # noqa: ARG002
        # bool is an int subclass; reject it explicitly.
        if isinstance(raw, bool) or not isinstance(raw, int | float):
            raise FieldValidationError("expected a number")
        return AnnotationValue(value_num=float(raw))

    def validate(self, field: Field, value: AnnotationValue) -> None:
        _only(value, "value_num")
        v = value.value_num
        if v is None:
            raise FieldValidationError("numeric field requires a value")
        if field.min is not None and v < field.min:
            raise FieldValidationError(f"value below min {field.min}")
        if field.max is not None and v > field.max:
            raise FieldValidationError(f"value above max {field.max}")
        if field.step is not None and field.min is not None:
            steps = (v - field.min) / field.step
            if abs(steps - round(steps)) > 1e-9:
                raise FieldValidationError(f"value not a multiple of step {field.step}")


class TextKind(FieldKind):
    def parse(self, field: Field, raw: object) -> AnnotationValue:  # noqa: ARG002
        if not isinstance(raw, str):
            raise FieldValidationError("expected a string")
        return AnnotationValue(value_text=raw)

    def validate(self, field: Field, value: AnnotationValue) -> None:  # noqa: ARG002
        _only(value, "value_text")
        if not value.value_text:
            raise FieldValidationError("text field requires a value")


class BooleanKind(FieldKind):
    def parse(self, field: Field, raw: object) -> AnnotationValue:
        if raw is None and field.nullable:
            return AnnotationValue()
        if not isinstance(raw, bool):
            raise FieldValidationError("expected a boolean")
        return AnnotationValue(value_bool=raw)

    def validate(self, field: Field, value: AnnotationValue) -> None:
        _only(value, "value_bool")
        if value.value_bool is None and not field.nullable:
            raise FieldValidationError("boolean field requires a value")
