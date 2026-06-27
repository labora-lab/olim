from repositron import Repository

from olim.dto import DatasetCreate, DatasetDTO
from olim.models import Dataset


class DatasetRepository(Repository[Dataset, DatasetDTO, DatasetCreate]):
    pass
