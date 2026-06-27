from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from olim.api.services import (
    AnnotationService,
    DatasetService,
    ItemService,
    PipelineService,
    SchemeService,
)
from olim.database import SessionLocal


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


def get_dataset_service(session: SessionDep) -> DatasetService:
    return DatasetService(session)


def get_item_service(session: SessionDep) -> ItemService:
    return ItemService(session)


def get_scheme_service(session: SessionDep) -> SchemeService:
    return SchemeService(session)


def get_annotation_service(session: SessionDep) -> AnnotationService:
    return AnnotationService(session)


def get_pipeline_service(session: SessionDep) -> PipelineService:
    return PipelineService(session)


DatasetServiceDep = Annotated[DatasetService, Depends(get_dataset_service)]
ItemServiceDep = Annotated[ItemService, Depends(get_item_service)]
SchemeServiceDep = Annotated[SchemeService, Depends(get_scheme_service)]
AnnotationServiceDep = Annotated[AnnotationService, Depends(get_annotation_service)]
PipelineServiceDep = Annotated[PipelineService, Depends(get_pipeline_service)]
