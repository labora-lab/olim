from pydantic import BaseModel

from olim.models import LabelMode


class SchemeCreateIn(BaseModel):
    name: str
    label_mode: LabelMode = "single"
    allow_extra_label: bool = False


class LabelCreateIn(BaseModel):
    name: str
