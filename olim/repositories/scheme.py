from repositron import Repository

from olim.dto import SchemeCreate, SchemeDTO
from olim.models import LabelScheme


class SchemeRepository(Repository[LabelScheme, SchemeDTO, SchemeCreate]):
    pass
