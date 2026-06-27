from pydantic import BaseModel

from olim.api.schemas.field import FieldIn


class SchemeCreateIn(BaseModel):
    name: str
    fields: list[FieldIn] = []
