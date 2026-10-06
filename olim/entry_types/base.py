"""Abstract base class for entry types in OLIM.

This module defines the interface that all entry types must implement,
providing a consistent contract for rendering, text extraction, search,
and upload functionality.
"""

from abc import ABC, abstractmethod
from collections.abc import Callable, Generator
from typing import Any, ClassVar

import pandas as pd


def strip_entry_id[T](value: T) -> T:
    """Trim surrounding whitespace from a text entry ID; other values pass through.

    An ID like "ABC " is invisible-different from "ABC" and breaks every later
    lookup (labels, queues, links), so IDs are trimmed when they enter OLIM.
    """
    return value.strip() if isinstance(value, str) else value  # type: ignore[return-value]


class EntryIdError(ValueError):
    """A row of an uploaded file has a missing or repeated entry ID.

    Attributes:
        kind: "empty" (row without ID) or "duplicate" (ID seen before)
        row: Line number in the file (the header is line 1)
        entry_id: The offending ID ("" for empty)
    """

    def __init__(self, kind: str, row: int, entry_id: str = "") -> None:
        super().__init__(f"{kind} entry id {entry_id!r} at row {row}")
        self.kind = kind
        self.row = row
        self.entry_id = entry_id


def prepare_id_column(chunk: pd.DataFrame, id_column: str) -> list[int]:
    """Trim the IDs of a chunk read from a CSV and reject empty or repeated ones.

    Only the chunk is inspected, so files of any size stream through; IDs repeated
    across chunks are caught when each batch is checked against the database.

    Args:
        chunk: Chunk from ``pd.read_csv(..., chunksize=...)``, modified in place
        id_column: Name of the ID column

    Returns:
        File line number of each row of the chunk

    Raises:
        EntryIdError: for the first row without an ID or with a repeated ID
    """
    chunk[id_column] = chunk[id_column].map(strip_entry_id)
    # pandas keeps counting the index across chunks; +2 for the header and 1-based lines
    rows = [int(i) + 2 for i in chunk.index]
    ids = chunk[id_column]

    empty = ids.isna() | (ids.astype(str) == "")
    if empty.any():
        raise EntryIdError("empty", rows[int(empty.to_numpy().argmax())])

    repeated = ids.duplicated()
    if repeated.any():
        position = int(repeated.to_numpy().argmax())
        raise EntryIdError("duplicate", rows[position], str(ids.iloc[position]))
    return rows


class EntryTypeBase(ABC):
    """Abstract base class for OLIM entry types.

    Each entry type defines how to:
    - Render entries for display in the UI
    - Extract text for machine learning and export
    - Search entries via Elasticsearch (optional)
    - Process upload batches from CSV files (optional)

    Subclasses must implement render() and extract_texts().
    Optional methods (search, generate_upload_batches) can be implemented
    as needed, otherwise they raise NotImplementedError.

    Class Attributes:
        entry_type: String identifier for this entry type (e.g., "single_text")
        template_path: Path to Jinja2 template for rendering
        show_metadata: Whether to display metadata in UI (default: True)
        supports_hiding: Whether entry type supports hiding functionality (default: False)
        custom_commands: Dict of custom commands for this entry type (default: {})
    """

    # Class-level constants (must be overridden by subclasses)
    entry_type: ClassVar[str]
    template_path: ClassVar[str]

    # Optional class-level settings
    show_metadata: ClassVar[bool] = True
    supports_hiding: ClassVar[bool] = False
    custom_commands: ClassVar[dict[str, Callable]] = {}

    @abstractmethod
    def render(self, entry_id: str, **kwargs) -> str | dict:
        """Render entry HTML for display.

        Args:
            entry_id: Unique entry identifier
            **kwargs: Additional parameters (may include dataset_id, highlight, etc.)

        Returns:
            Rendered HTML string

        Raises:
            ValueError: If required parameters are missing
        """
        ...

    @abstractmethod
    def extract_texts(self, entry_id: str, **kwargs) -> pd.DataFrame:
        """Extract text content for ML/export.

        Args:
            entry_id: Unique entry identifier
            **kwargs: Additional parameters (may include dataset_id, only_ids, only_values, etc.)

        Returns:
            DataFrame with at minimum: entry_id column and text column
            May include additional columns depending on entry type

        Raises:
            ValueError: If required parameters are missing
        """
        ...

    def search(
        self,
        _must_terms: list[str],
        _must_phrases: list[str],
        _not_must_terms: list[str],
        _not_must_phrases: list[str],
        _number: int,
        **_kwargs,
    ) -> list[dict]:
        """Search entries via Elasticsearch.

        Optional method - only implement if entry type supports search.

        Args:
            _must_terms: Terms that should appear (OR logic)
            _must_phrases: Exact phrases that should appear (OR logic)
            _not_must_terms: Terms that must not appear (AND NOT logic)
            _not_must_phrases: Phrases that must not appear (AND NOT logic)
            _number: Maximum number of results to return
            **_kwargs: Additional parameters (may include dataset_id, etc.)

        Returns:
            List of dicts with keys:
                - entry_id: str
                - match_count: int
                - description: str
                - score: float
                - type: str (entry type identifier)

        Raises:
            NotImplementedError: If entry type doesn't support search
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement search functionality"
        )

    def search_regex(
        self,
        _pattern: str,
        _number: int,
        **_kwargs,
    ) -> list[dict]:
        """Search entries by Python regex applied over text content.

        Optional method - only implement if entry type supports regex search.

        Args:
            _pattern: Python regex pattern (case-insensitive)
            _number: Maximum number of results to return
            **_kwargs: Additional parameters (may include dataset_id, etc.)

        Returns:
            List of dicts with keys: entry_id, description, type

        Raises:
            NotImplementedError: If entry type doesn't support regex search
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement regex search functionality"
        )

    def generate_upload_batches(
        self,
        _filename: str,
        _id_column: str,
        _text_column: str,
        _batch_size: int = 1000,
        **_kwargs,
    ) -> Generator[list[dict[str, Any]]]:
        """Generate batches of data for upload from CSV file.

        Optional method - only implement if entry type supports CSV upload.

        Args:
            _filename: Path to CSV file
            _id_column: Name of column containing entry IDs
            _text_column: Name of column containing text content
            _batch_size: Number of entries per batch (default: 1000)
            **_kwargs: Additional parameters specific to entry type

        Yields:
            Batches of entries in format:
            [
                {
                    "id": "entry_123",
                    "text": "Text content here",
                    "metadata": {"key": "value", ...}
                },
                ...
            ]

        Raises:
            NotImplementedError: If entry type doesn't support upload
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not implement upload batch generation"
        )

    # Extension methods for special entry types

    def get_all_hidden(self, _project_id: int) -> list[dict]:
        """Get all hidden entries for a project.

        Optional method - only for entry types with hiding functionality.

        Args:
            _project_id: ID of the project

        Returns:
            List of dicts with hidden entry information

        Raises:
            NotImplementedError: If entry type doesn't support hiding
        """
        raise NotImplementedError(f"{self.__class__.__name__} does not support hiding entries")

    def have_hidden(self) -> bool:
        """Check if entry type has hidden entries.

        Optional method - only for entry types with hiding functionality.

        Returns:
            True if entry type supports hiding, False otherwise
        """
        return False

    @classmethod
    def get_template_path(cls) -> str:
        """Get the Jinja2 template path for rendering.

        Returns:
            Template path string (e.g., "entry_types/single_text.html")
        """
        return cls.template_path

    @classmethod
    def get_entry_type(cls) -> str:
        """Get the entry type identifier.

        Returns:
            Entry type string (e.g., "single_text", "patient")
        """
        return cls.entry_type
