from dataclasses import replace

from repositron import Repository, on, writes

from olim.dto import FieldDTO, OptionDTO, SchemeCreate, SchemeDTO
from olim.dto.field import FieldSpec
from olim.models import Field, Option, Scheme


class SchemeRepository(Repository[Scheme, SchemeDTO, SchemeCreate]):
    @on("hydrate", mode="after")
    def with_fields(self, model: Scheme, dto: SchemeDTO) -> SchemeDTO:
        """Attach the full field/option tree on every read."""
        return replace(dto, fields=[self._field_dto(f) for f in model.fields])

    @writes
    def create_tree(
        self,
        payload: SchemeCreate,
        fields: list[FieldSpec],
        *,
        commit: bool | None = None,  # noqa: ARG002  consumed by @writes
    ) -> int:
        """Create a scheme with its fields and options in one transaction."""
        scheme = Scheme(dataset_id=payload.dataset_id, name=payload.name)
        self.session.add(scheme)
        self.session.flush()  # need scheme.id for the fields
        for spec in fields:
            field = Field(
                scheme_id=scheme.id,
                name=spec.name,
                type=spec.type,
                min=spec.min,
                max=spec.max,
                step=spec.step,
                multi=spec.multi,
                allow_other=spec.allow_other,
                nullable=spec.nullable,
            )
            self.session.add(field)
            self.session.flush()  # need field.id for its options
            for name in spec.options:
                self.session.add(Option(field_id=field.id, name=name))
        return scheme.id

    def list_by_dataset(self, dataset_id: int) -> list[SchemeDTO]:
        return self.list(dataset_id=dataset_id)

    def _field_dto(self, field: Field) -> FieldDTO:
        return FieldDTO(
            id=field.id,
            scheme_id=field.scheme_id,
            name=field.name,
            type=field.type,
            min=field.min,
            max=field.max,
            step=field.step,
            multi=field.multi,
            allow_other=field.allow_other,
            nullable=field.nullable,
            options=[
                OptionDTO(id=o.id, field_id=o.field_id, name=o.name)
                for o in field.options
            ],
        )
