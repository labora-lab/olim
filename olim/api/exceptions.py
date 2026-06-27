from typing import Any


class APIError(Exception):
    """Base for errors the API maps to an HTTP response via a global handler."""

    status_code: int = 400

    def __init__(self, detail: Any) -> None:
        super().__init__(str(detail))
        self.detail = detail


class NotFoundError(APIError):
    status_code = 404


class DatasetNotFoundError(NotFoundError):
    def __init__(self, dataset_id: int) -> None:
        super().__init__(f"dataset {dataset_id} not found")
        self.dataset_id = dataset_id


class SchemeNotFoundError(NotFoundError):
    def __init__(self, scheme_id: int) -> None:
        super().__init__(f"scheme {scheme_id} not found")
        self.scheme_id = scheme_id


class ItemNotFoundError(NotFoundError):
    def __init__(self, item_id: int) -> None:
        super().__init__(f"item {item_id} not found")
        self.item_id = item_id


class FieldNotFoundError(NotFoundError):
    def __init__(self, field_id: int) -> None:
        super().__init__(f"field {field_id} not found")
        self.field_id = field_id


class PipelineNotFoundError(NotFoundError):
    def __init__(self, pipeline_id: int) -> None:
        super().__init__(f"pipeline {pipeline_id} not found")
        self.pipeline_id = pipeline_id


class BlockNotApplicableError(APIError):
    """A block can't be appended: its required inputs aren't available yet at
    this point in the pipeline."""

    status_code = 422

    def __init__(self, block_type: str, missing: list[str]) -> None:
        super().__init__(
            f"block {block_type!r} needs {missing} which are not available here"
        )
        self.block_type = block_type
        self.missing = missing


class AnnotationValidationError(APIError):
    """One or more answers in a batch failed validation. All-or-nothing, so the
    batch is rejected and every error is reported together."""

    status_code = 422

    def __init__(self, errors: dict[int, str]) -> None:
        # field_id -> message
        super().__init__([
            {"field_id": fid, "error": msg} for fid, msg in errors.items()
        ])
        self.errors = errors
