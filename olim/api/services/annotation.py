from sqlalchemy import select
from sqlalchemy.orm import Session

from olim.api.exceptions import (
    AnnotationValidationError,
    FieldNotFoundError,
    ItemNotFoundError,
)
from olim.api.schemas.annotation import AnswerIn
from olim.dto import AnnotationDTO
from olim.fields import AnnotationValue, FieldValidationError, kind_for
from olim.models import AnnotationSource, Field, Item
from olim.repositories import AnnotationRepository

_list = list


class AnnotationService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = AnnotationRepository(session)

    def set_answers(
        self,
        item_id: int,
        answers: _list[AnswerIn],
        *,
        source: AnnotationSource = "human",
    ) -> _list[AnnotationDTO]:
        if not self.session.get(Item, item_id):
            raise ItemNotFoundError(item_id)

        fields = self._load_fields(a.field_id for a in answers)
        items: list[tuple[Field, AnnotationValue]] = []
        errors: dict[int, str] = {}
        for answer in answers:
            field = fields[answer.field_id]
            kind = kind_for(field.type)
            try:
                value = kind.parse(field, answer.value)
                kind.validate(field, value)
            except FieldValidationError as e:
                errors[answer.field_id] = str(e)
            else:
                items.append((field, value))

        if errors:
            raise AnnotationValidationError(errors)  # all-or-nothing: nothing saved

        return self.repo.set_answers(item_id, source, items, commit=True)

    def list(self, item_id: int) -> _list[AnnotationDTO]:
        return self.repo.list(item_id=item_id)

    def _load_fields(self, field_ids) -> dict[int, Field]:
        wanted = set(field_ids)
        found = self.session.scalars(select(Field).where(Field.id.in_(wanted))).all()
        fields = {f.id: f for f in found}
        for fid in wanted:
            if fid not in fields:
                raise FieldNotFoundError(fid)
        return fields
