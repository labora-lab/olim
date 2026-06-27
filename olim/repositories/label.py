from repositron import Repository

from olim.dto import LabelCreate, LabelDTO
from olim.models import Label


class LabelRepository(Repository[Label, LabelDTO, LabelCreate]):
    pass
