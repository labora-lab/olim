from repositron import Repository

from olim.dto import AnnotationCreate, AnnotationDTO
from olim.models import Annotation


class AnnotationRepository(Repository[Annotation, AnnotationDTO, AnnotationCreate]):
    pass
