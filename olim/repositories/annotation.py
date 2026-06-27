from repositron import Repository, on, writes
from sqlalchemy import delete

from olim.dto import AnnotationCreate, AnnotationDTO
from olim.fields import AnnotationValue
from olim.models import Annotation, AnnotationSource, Field


class AnnotationRepository(Repository[Annotation, AnnotationDTO, AnnotationCreate]):
    @on("hydrate", mode="build")
    def build(self, model: Annotation) -> AnnotationDTO:
        # the DTO exposes a single `value`; the model's property picks the right
        # column, so the automatic by-name build can't do it.
        return AnnotationDTO(
            id=model.id,
            item_id=model.item_id,
            field_id=model.field_id,
            source=model.source,
            value=model.value,
        )

    @writes
    def set_answers(
        self,
        item_id: int,
        source: AnnotationSource,
        items: list[tuple[Field, AnnotationValue]],
        *,
        commit: bool | None = None,  # noqa: ARG002  consumed by @writes
    ) -> list[AnnotationDTO]:
        """Upsert answers for one item in one transaction. Each field's prior
        answers (for this source) are replaced by the submitted value. A select
        field carries its full option set, so single and multi reconcile the
        same way: clear the field, then insert the new rows."""
        saved: list[Annotation] = []
        for field, value in items:
            self.session.execute(
                delete(Annotation).where(
                    Annotation.item_id == item_id,
                    Annotation.field_id == field.id,
                    Annotation.source == source,
                )
            )
            saved += self._rows_for(item_id, source, field, value)
        self.session.flush()
        # _hydrate_one routes through the build hook; _hydrate would skip it.
        return [self._hydrate_one(row) for row in saved]

    def _rows_for(
        self,
        item_id: int,
        source: AnnotationSource,
        field: Field,
        value: AnnotationValue,
    ) -> list[Annotation]:
        fid = field.id
        if value.option_ids is not None:
            rows = [
                Annotation.at(item_id, fid, source, option_id=oid)
                for oid in value.option_ids
            ]
            if value.value_text is not None:  # select with allow_other
                rows.append(
                    Annotation.at(item_id, fid, source, value_text=value.value_text)
                )
        else:
            rows = [
                Annotation.at(
                    item_id,
                    fid,
                    source,
                    value_num=value.value_num,
                    value_text=value.value_text,
                    value_bool=value.value_bool,
                )
            ]
        for row in rows:
            self.session.add(row)
        return rows
