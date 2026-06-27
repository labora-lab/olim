from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from olim.models import Field


class FieldValidationError(Exception):
    """A submitted annotation value is invalid for its field. The API layer
    maps this to a 400."""


@dataclass(frozen=True, slots=True)
class AnnotationValue:
    """The value an annotator submits for a field, decided by the field's kind:
    select uses option_ids (a one-element list when not multi); numeric/text/
    boolean use their value_* attribute."""

    option_ids: list[int] | None = None
    value_num: float | None = None
    value_text: str | None = None
    value_bool: bool | None = None


class FieldKind:
    """Rules for one field type: how to read the client's raw value, which value
    a field of this type accepts, and how to validate it. One subclass per
    FieldType; the registry dispatches. Adding a type is one new subclass."""

    def parse(self, field: Field, raw: object) -> AnnotationValue:
        """Turn the client's single `value` into the typed AnnotationValue for
        this field's column. Raise FieldValidationError on a wrong-shaped value."""
        raise NotImplementedError

    def validate(self, field: Field, value: AnnotationValue) -> None:
        """Raise FieldValidationError if `value` is not valid for `field`."""
        raise NotImplementedError

    def allows_duplicate(self, field: Field) -> bool:  # noqa: ARG002
        """Whether one (item, field, source) may carry more than one annotation
        (e.g. multi-select). Single-valued kinds return False."""
        return False
