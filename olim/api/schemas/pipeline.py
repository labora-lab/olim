from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from olim.pipelines import BlockType


class _BlockInBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LowercaseBlockIn(_BlockInBase):
    type: Literal["lowercase"]


class StripStopwordsBlockIn(_BlockInBase):
    type: Literal["strip_stopwords"]


class TfidfBlockIn(_BlockInBase):
    type: Literal["tfidf"]
    max_features: Annotated[int, Field(gt=0)] | None = None
    ngram_max: Annotated[int, Field(ge=1)] = 1


class CountVectorizerBlockIn(_BlockInBase):
    type: Literal["count_vectorizer"]
    max_features: Annotated[int, Field(gt=0)] | None = None
    ngram_max: Annotated[int, Field(ge=1)] = 1


class TrainTestSplitBlockIn(_BlockInBase):
    type: Literal["train_test_split"]
    test_size: Annotated[float, Field(gt=0, lt=1)] = 0.2


class TrainCalibTestSplitBlockIn(_BlockInBase):
    type: Literal["train_calib_test_split"]
    test_size: Annotated[float, Field(gt=0, lt=1)] = 0.2
    calib_size: Annotated[float, Field(gt=0, lt=1)] = 0.2


class LogRegBlockIn(_BlockInBase):
    type: Literal["logreg"]
    C: Annotated[float, Field(gt=0)] = 1.0


class RandomForestBlockIn(_BlockInBase):
    type: Literal["random_forest"]
    n_estimators: Annotated[int, Field(gt=0)] = 100


class XGBoostBlockIn(_BlockInBase):
    type: Literal["xgboost"]
    n_estimators: Annotated[int, Field(gt=0)] = 100
    learning_rate: Annotated[float, Field(gt=0)] = 0.3


class ConformalBlockIn(_BlockInBase):
    type: Literal["conformal"]
    alpha: Annotated[float, Field(gt=0, lt=1)] = 0.1


class ClassificationMetricsBlockIn(_BlockInBase):
    type: Literal["classification_metrics"]


class PickleArtifactBlockIn(_BlockInBase):
    type: Literal["pickle_artifact"]


BlockIn = Annotated[
    LowercaseBlockIn
    | StripStopwordsBlockIn
    | TfidfBlockIn
    | CountVectorizerBlockIn
    | TrainTestSplitBlockIn
    | TrainCalibTestSplitBlockIn
    | LogRegBlockIn
    | RandomForestBlockIn
    | XGBoostBlockIn
    | ConformalBlockIn
    | ClassificationMetricsBlockIn
    | PickleArtifactBlockIn,
    Field(discriminator="type"),
]

_CONFIG_MODELS: dict[BlockType, type[_BlockInBase]] = {
    "lowercase": LowercaseBlockIn,
    "strip_stopwords": StripStopwordsBlockIn,
    "tfidf": TfidfBlockIn,
    "count_vectorizer": CountVectorizerBlockIn,
    "train_test_split": TrainTestSplitBlockIn,
    "train_calib_test_split": TrainCalibTestSplitBlockIn,
    "logreg": LogRegBlockIn,
    "random_forest": RandomForestBlockIn,
    "xgboost": XGBoostBlockIn,
    "conformal": ConformalBlockIn,
    "classification_metrics": ClassificationMetricsBlockIn,
    "pickle_artifact": PickleArtifactBlockIn,
}


def config_schema_for(block_type: BlockType) -> dict:
    return _CONFIG_MODELS[block_type].model_json_schema()


class PipelineCreateIn(BaseModel):
    name: str


class CandidateOut(BaseModel):
    """A block that may be appended next, with its config schema for the form."""

    type: BlockType
    category: str
    consumes: list[str]
    produces: list[str]
    config_schema: dict
