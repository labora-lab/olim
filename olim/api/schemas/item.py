from pydantic import BaseModel


class ItemUpload(BaseModel):
    contents: list[str]
