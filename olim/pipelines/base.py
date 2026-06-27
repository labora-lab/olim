from dataclasses import dataclass
from typing import Literal

# The "data shape" available at a point in the pipeline. Opaque tokens: a block
# consumes some and produces others; compatibility is pure set membership. No
# payload (matrix width, n_classes) — that's an execution-time concern.
PipelineCapability = Literal[
    "raw_text",  # seeded by a text dataset
    "labels",  # seeded because a scheme is always attached (the supervision target)
    "clean_text",  # produced by preprocessing
    "features",  # produced by vectorization
    "split",  # produced by a 2-way train/test split
    "calibration",  # produced by a 3-way split — required by conformal
    "model",  # produced by an estimator
    "predictions",  # produced by evaluation/scoring
]

# A block's type (the pydantic discriminator) and its UI grouping category.
BlockType = Literal[
    "lowercase",
    "strip_stopwords",
    "tfidf",
    "count_vectorizer",
    "train_test_split",
    "train_calib_test_split",
    "logreg",
    "random_forest",
    "xgboost",
    "conformal",
    "classification_metrics",
    "pickle_artifact",
]
BlockCategory = Literal[
    "source", "clean", "vectorize", "split", "model", "eval", "postprocess", "store"
]


class PipelineCompatibilityError(Exception):
    """A block can't be appended because its required inputs aren't available at
    that point. The API layer maps this to a 422."""


@dataclass(frozen=True, slots=True)
class BlockKind:
    """Static descriptor of one block type: what it consumes and produces, for
    the "what fits next" engine. Pure data — no behavior (fit/transform) until an
    execution layer exists. Adding a block = one entry in the catalog registry."""

    type: BlockType
    category: BlockCategory
    consumes: frozenset[PipelineCapability]
    produces: frozenset[PipelineCapability]
