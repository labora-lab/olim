from olim.pipelines.base import BlockCategory, BlockKind, BlockType, PipelineCapability


def _kind(
    type_: BlockType,
    category: BlockCategory,
    consumes: tuple[PipelineCapability, ...],
    produces: tuple[PipelineCapability, ...],
) -> BlockKind:
    return BlockKind(type_, category, frozenset(consumes), frozenset(produces))


_BLOCKS: dict[BlockType, BlockKind] = {
    "lowercase": _kind("lowercase", "clean", ("raw_text",), ("clean_text",)),
    "strip_stopwords": _kind(
        "strip_stopwords", "clean", ("clean_text",), ("clean_text",)
    ),
    "tfidf": _kind("tfidf", "vectorize", ("clean_text",), ("features",)),
    "count_vectorizer": _kind(
        "count_vectorizer", "vectorize", ("clean_text",), ("features",)
    ),
    "train_test_split": _kind(
        "train_test_split", "split", ("features", "labels"), ("split",)
    ),
    "train_calib_test_split": _kind(
        "train_calib_test_split",
        "split",
        ("features", "labels"),
        ("split", "calibration"),
    ),
    "logreg": _kind("logreg", "model", ("features", "labels", "split"), ("model",)),
    "random_forest": _kind(
        "random_forest", "model", ("features", "labels", "split"), ("model",)
    ),
    "xgboost": _kind("xgboost", "model", ("features", "labels", "split"), ("model",)),
    "conformal": _kind(
        "conformal", "postprocess", ("model", "calibration"), ("model",)
    ),
    "classification_metrics": _kind(
        "classification_metrics", "eval", ("model", "split"), ("predictions",)
    ),
    "pickle_artifact": _kind("pickle_artifact", "store", ("model",), ()),
}


def kind_for(block_type: BlockType) -> BlockKind:
    return _BLOCKS[block_type]


def all_kinds() -> list[BlockKind]:
    return list(_BLOCKS.values())
