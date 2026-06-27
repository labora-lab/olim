from repositron import Repository

from olim.dto import OptionCreate, OptionDTO
from olim.models import Option


class OptionRepository(Repository[Option, OptionDTO, OptionCreate]):
    pass
