from repositron import Repository

from olim.dto import FieldCreate, FieldDTO
from olim.models import Field


class FieldRepository(Repository[Field, FieldDTO, FieldCreate]):
    pass
