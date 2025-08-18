from abc import abstractmethod
from typing import Any

import numpy as np
from lightgbm import LGBMClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import (
    LogisticRegression,
    QuantileRegressor as LinearQuantileRegressor,
)
from sklearn.tree import DecisionTreeClassifier
from xgboost import XGBClassifier

from . import ClassificationModel, RegressionModel


class TfidfSklearnClassificationModel(ClassificationModel):
    def __init__(
        self,
        *args,
        ngram_range: tuple[int, int] = (1, 1),
        n_classes: int | None = None,
        **kwargs,
    ) -> None:
        self.n_classes = n_classes
        self.embedding = TfidfVectorizer(ngram_range=ngram_range)
        self.model = self._create_model(*args, **kwargs)

    @abstractmethod
    def _create_model(self, *args, **kwargs) -> Any:  # noqa: ANN401
        pass

    def train(self, labelled_data: list[tuple[str, int]]) -> None:
        unlabelled_data = [text for text, label in labelled_data]
        labels = [label for text, label in labelled_data]

        available_labels = np.unique(labels)
        if self.n_classes is None:
            self.n_classes = len(available_labels)

        self.label_mapping = dict(enumerate(available_labels))
        self.inv_label_mapping = {y: i for i, y in enumerate(available_labels)}
        encoded_labels = [self.inv_label_mapping[y] for y in labels]

        self.embedding.fit(unlabelled_data)

        feature_matrix = self.embedding.transform(unlabelled_data)
        self.model.fit(feature_matrix, encoded_labels)

    def get_embeddings(self, data: list[str]) -> list[list[float]]:
        return self.embedding.transform(data)

    def predict(self, unlabelled_data: list[str]) -> list[int]:
        if len(unlabelled_data) == 0:
            return []
        feature_matrix = self.embedding.transform(unlabelled_data)
        return [self.label_mapping[pred] for pred in self.model.predict(feature_matrix)]

    def predict_proba(self, unlabelled_data: list[str]) -> list[dict[int, float]]:
        if len(unlabelled_data) == 0:
            return []
        feature_matrix = self.embedding.transform(unlabelled_data)
        probas = self.model.predict_proba(feature_matrix)
        return probas


class TfidfSklearnQuantileRegressionModel(RegressionModel):
    def __init__(
        self,
        *args,
        ngram_range: tuple[int, int] = (1, 1),
        alpha: float = 0.05,
        conformalize: bool = False,
        **kwargs,
    ) -> None:
        self.conformalize = conformalize
        self.embedding = TfidfVectorizer(ngram_range=ngram_range)

        self.model_lower = self._create_model(alpha, *args, **kwargs)
        self.model_upper = self._create_model(1 - alpha, *args, **kwargs)

    @abstractmethod
    def _create_model(self, quantile: float, *args, **kwargs) -> Any:  # noqa: ANN401
        pass

    def train(self, labelled_data: list[tuple[str, float]]) -> None:
        if self.conformalize:
            raise NotImplementedError

        unlabelled_data = [text for text, label in labelled_data]
        labels = [label for text, label in labelled_data]

        self.embedding.fit(unlabelled_data)

        feature_matrix = self.embedding.transform(unlabelled_data)
        self.model_lower.fit(feature_matrix, labels)
        self.model_upper.fit(feature_matrix, labels)

    def get_embeddings(self, data: list[str]) -> list[list[float]]:
        return self.embedding.transform(data)

    def predict(self, unlabelled_data: list[str]) -> list[float]:
        return [(inf + sup) * 0.5 for inf, sup in self.predict_interval(unlabelled_data)]

    def predict_interval(self, unlabelled_data: list[str]) -> list[tuple[float, float]]:
        if self.conformalize:
            raise NotImplementedError

        feature_matrix = self.embedding.transform(unlabelled_data)
        preds_lower = self.model_lower.predict(feature_matrix)
        preds_upper = self.model_upper.predict(feature_matrix)
        return list(zip(preds_lower, preds_upper, strict=False))


class TfidfLogisticRegressionClassifier(TfidfSklearnClassificationModel):
    def _create_model(self, *args, **kwargs) -> Any:  # noqa: ANN401
        return LogisticRegression(*args, **kwargs, random_state=0)


class TfidfDecisionTreeClassifier(TfidfSklearnClassificationModel):
    def _create_model(self, *args, **kwargs) -> Any:  # noqa: ANN401
        return DecisionTreeClassifier(*args, **kwargs, random_state=0)


class TfidfXGBoostClassifier(TfidfSklearnClassificationModel):
    def _create_model(self, *args, **kwargs) -> Any:  # noqa: ANN401
        return XGBClassifier(*args, **kwargs, random_state=0)


class TfidfLightGBMClassifier(TfidfSklearnClassificationModel):
    def _create_model(self, *args, **kwargs) -> Any:  # noqa: ANN401
        return LGBMClassifier(*args, **kwargs, random_state=0)


class TfidfLinearRegressionRegressor(TfidfSklearnQuantileRegressionModel):
    def _create_model(self, quantile: float, *args, **kwargs) -> Any:  # noqa: ANN401
        return LinearQuantileRegressor(*args, quantile=quantile, **kwargs)


class TfidfLightGBMRegressor(TfidfSklearnQuantileRegressionModel):
    def _create_model(self, quantile: float, *args, **kwargs) -> Any:  # noqa: ANN401
        return LGBMClassifier(
            *args,
            **kwargs,
            random_state=0,
            objective="quantile",
            metric="quantile",
            alpha=quantile,
        )
