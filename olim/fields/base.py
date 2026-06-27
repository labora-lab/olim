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
    """The typed value an annotator submits for a field. Exactly one of these
    is set, decided by the field's kind."""

    option_id: int | None = None
    value_num: float | None = None
    value_text: str | None = None
    value_bool: bool | None = None


class FieldKind:
    """Rules for one field type: which value a field of this type accepts and
    how to validate it. One subclass per FieldType; the registry dispatches."""

    def validate(self, field: Field, value: AnnotationValue) -> None:
        """Raise FieldValidationError if `value` is not valid for `field`."""
        raise NotImplementedError

    def allows_duplicate(self, field: Field) -> bool:  # noqa: ARG002
        """Whether one (item, field, source) may carry more than one annotation
        (e.g. multi-select). Single-valued kinds return False."""
        return False
