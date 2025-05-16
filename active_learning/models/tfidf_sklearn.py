from typing import Any
from abc import ABC, abstractmethod

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import (
    LogisticRegression,
    QuantileRegressor as LinearQuantileRegressor,
)
from sklearn.tree import DecisionTreeClassifier
from xgboost import XGBClassifier
from lightgbm import LGBMClassifier

from . import ClassificationModel, RegressionModel


class TfidfSklearnClassificationModel(ClassificationModel):
    def __init__(
        self,
        *args,
        ngram_range: tuple[int, int] = (1, 1),
        n_classes: int | None = None,
        **kwargs
    ):
        self.n_classes = n_classes
        self.embedding = TfidfVectorizer(ngram_range=ngram_range)
        self.model = self._create_model(*args, **kwargs)

    @abstractmethod
    def _create_model(self, *args, **kwargs) -> Any:
        pass

    def train(self, labelled_data: list[tuple[str, int]]) -> None:
        unlabelled_data = [text for text, label in labelled_data]
        labels = [label for text, label in labelled_data]

        available_labels = np.unique(labels)
        if self.n_classes is None:
            self.n_classes = len(available_labels)

        self.label_mapping = {i: y for i, y in enumerate(available_labels)}
        self.inv_label_mapping = {y: i for i, y in enumerate(available_labels)}
        encoded_labels = [self.inv_label_mapping[y] for y in labels]

        self.embedding.fit(unlabelled_data)

        X = self.embedding.transform(unlabelled_data)
        self.model.fit(X, encoded_labels)

    def get_embeddings(self, data: list[str]) -> list[list[float]]:
        return self.embedding.transform(data)

    def predict(self, unlabelled_data: list[str]) -> list[int]:
        if len(unlabelled_data) == 0:
            return []
        X = self.embedding.transform(unlabelled_data)
        return [self.label_mapping[pred] for pred in self.model.predict(X)]

    def predict_proba2(self, unlabelled_data: list[str]) -> list[dict[int, float]]:
        if len(unlabelled_data) == 0:
            return []
        X = self.embedding.transform(unlabelled_data)
        probas = self.model.predict_proba(X)
        return probas

    def predict_proba(self, unlabelled_data: list[str]) -> list[list[float]]:
        if len(unlabelled_data) == 0:
            return []
        X = self.embedding.transform(unlabelled_data)
        probas = self.model.predict_proba(X)
        # return [{j: probas[i, j] for j in range(probas.shape[1])} for i in range(probas.shape[0])]
        return [
            {y: 0 for y in range(self.n_classes)}
            | {y: probas[i, j] for y, j in self.inv_label_mapping.items()}
            for i in range(probas.shape[0])
        ]


class TfidfSklearnQuantileRegressionModel(RegressionModel):
    def __init__(
        self,
        *args,
        ngram_range: tuple[int, int] = (1, 1),
        alpha: float = 0.05,
        conformalize: bool = False,
        **kwargs
    ):
        self.conformalize = conformalize
        self.embedding = TfidfVectorizer(ngram_range=ngram_range)

        self.model_lower = self._create_model(alpha, *args, **kwargs)
        self.model_upper = self._create_model(1 - alpha, *args, **kwargs)

    @abstractmethod
    def _create_model(self, quantile: float, *args, **kwargs) -> Any:
        pass

    def train(self, labelled_data: list[tuple[str, float]]) -> None:
        if self.conformalize:
            raise NotImplementedError

        unlabelled_data = [text for text, label in labelled_data]
        labels = [label for text, label in labelled_data]

        self.embedding.fit(unlabelled_data)

        X = self.embedding.transform(unlabelled_data)
        self.model_lower.fit(X, labels)
        self.model_upper.fit(X, labels)

    def get_embeddings(self, data: list[str]) -> list[list[float]]:
        return self.embedding.transform(data)

    def predict(self, unlabelled_data: list[str]) -> list[float]:
        return [
            (inf + sup) * 0.5 for inf, sup in self.predict_interval(unlabelled_data)
        ]

    def predict_interval(self, unlabelled_data: list[str]) -> list[tuple[float, float]]:
        if self.conformalize:
            raise NotImplementedError

        X = self.embedding.transform(unlabelled_data)
        preds_lower = self.model_lower.predict(X)
        preds_upper = self.model_upper.predict(X)
        return list(zip(preds_lower, preds_upper))


class TfidfLogisticRegressionClassifier(TfidfSklearnClassificationModel):
    def _create_model(self, *args, **kwargs) -> Any:
        return LogisticRegression(*args, **kwargs, random_state=0)


class TfidfDecisionTreeClassifier(TfidfSklearnClassificationModel):
    def _create_model(self, *args, **kwargs) -> Any:
        return DecisionTreeClassifier(*args, **kwargs, random_state=0)


class TfidfXGBoostClassifier(TfidfSklearnClassificationModel):
    def _create_model(self, *args, **kwargs) -> Any:
        return XGBClassifier(*args, **kwargs, random_state=0)


class TfidfLightGBMClassifier(TfidfSklearnClassificationModel):
    def _create_model(self, *args, **kwargs) -> Any:
        return LGBMClassifier(*args, **kwargs, random_state=0)


class TfidfLinearRegressionRegressor(TfidfSklearnQuantileRegressionModel):
    def _create_model(self, quantile, *args, **kwargs) -> Any:
        return LinearQuantileRegressor(quantile=quantile, *args, **kwargs)


class TfidfLightGBMRegressor(TfidfSklearnQuantileRegressionModel):
    def _create_model(self, quantile, *args, **kwargs) -> Any:
        return LGBMClassifier(
            *args,
            **kwargs,
            random_state=0,
            objective="quantile",
            metric="quantile",
            alpha=quantile
        )
