from pathlib import Path
from typing import Protocol

from olim.config import ARTIFACT_ROOT


class ArtifactStore(Protocol):
    """Moves opaque bytes between blocks. Serialization is the runner's job, so
    the store never imports sklearn and an S3 impl is a drop-in swap."""

    def put(self, run_id: int, position: int, payload: bytes) -> str:
        """Store one block's output, returning an opaque ref to retrieve it."""
        ...

    def get(self, ref: str) -> bytes:
        """Read back the bytes for a ref produced by `put`."""
        ...


class LocalArtifactStore:
    """Stores artifacts on disk under a per-run directory. The ref is the path
    relative to the root, so cleaning a run is `rmtree(root / "runs" / run_id)`."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def put(self, run_id: int, position: int, payload: bytes) -> str:
        ref = f"runs/{run_id}/{position}.pkl"
        path = self.root / ref
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return ref

    def get(self, ref: str) -> bytes:
        return (self.root / ref).read_bytes()


def get_store() -> ArtifactStore:
    return LocalArtifactStore(Path(ARTIFACT_ROOT))
