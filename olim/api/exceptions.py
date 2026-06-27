class APIError(Exception):
    """Base for errors the API maps to an HTTP response via a global handler."""

    status_code: int = 400

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
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
