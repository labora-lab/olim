from olim.fields.base import FieldKind
from olim.fields.kinds import BooleanKind, NumericKind, SelectKind, TextKind
from olim.models import FieldType

_KINDS: dict[FieldType, FieldKind] = {
    "select": SelectKind(),
    "numeric": NumericKind(),
    "text": TextKind(),
    "boolean": BooleanKind(),
}


def kind_for(field_type: FieldType) -> FieldKind:
    return _KINDS[field_type]
