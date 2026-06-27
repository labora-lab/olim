from repositron import Repository

from olim.dto import ItemCreate, ItemDTO
from olim.models import Item


class ItemRepository(Repository[Item, ItemDTO, ItemCreate]):
    pass
