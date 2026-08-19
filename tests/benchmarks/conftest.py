from pathlib import Path

import pytest

from .harness import REVIEWS_CSV, load_corpus

CORPUS_ROWS = 20_000
HERE = Path(__file__).parent


def pytest_collection_modifyitems(config, items):
    """Mark this directory's tests slow — deselect with -m 'not slow'.

    The hook is handed every collected item, not just this package's, so the path
    check is what keeps it from marking the whole suite.
    """
    for item in items:
        if HERE in Path(str(item.fspath)).parents:
            item.add_marker(pytest.mark.slow)


@pytest.fixture(scope="session")
def corpus():
    if not REVIEWS_CSV.exists():
        pytest.skip(f"{REVIEWS_CSV.name} not present — see tests/benchmarks/README.md")
    return load_corpus(n_rows=CORPUS_ROWS)
