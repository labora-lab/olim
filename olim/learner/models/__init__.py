from abc import ABC, abstractmethod
from typing import Any

import numpy as np
import xgboost as xgb


class ClassificationModel(ABC):
    @abstractmethod
    def train(self, labelled_data: list[tuple[str, int]]) -> None:
        pass

    @abstractmethod
    def predict(self, unlabelled_data: list[str]) -> list[int]:
        pass

    @abstractmethod
    def get_embeddings(self, data: list[str]) -> list[list[float]]:
        pass

    @abstractmethod
    def predict_proba(self, unlabelled_data: list[str]) -> list[dict[int, float]]:
        pass


class RegressionModel(ABC):
    @abstractmethod
    def train(self, labelled_data: list[tuple[str, float]]) -> None:
        pass

    @abstractmethod
    def predict(self, unlabelled_data: list[str]) -> list[float]:
        pass

    @abstractmethod
    def get_embeddings(self, data: list[str]) -> list[list[float]]:
        pass

    @abstractmethod
    def predict_interval(self, unlabelled_data: list[str]) -> list[tuple[float, float]]:
        pass


class DummyClassificationModel(ClassificationModel):
    def __init__(self, *, n_classes: int):
        self.n_classes = n_classes
        self._rng = np.random.default_rng(0)

    def train(self, labelled_data, validation) -> None:
        pass

    def predict(self, unlabelled_data):
        return [
            max(scores.items(), key=lambda x: x[1])[0]
            for scores in self.predict_proba(unlabelled_data)
        ]

    def get_embeddings(self, data: list[str]) -> list[list[float]]:
        n = len(data)
        return self._rng.uniform(0, 1, size=(n, 3))

    def predict_proba(self, unlabelled_data: list[str]) -> list[dict[int, float]]:
        n = len(unlabelled_data)

        scores = self._rng.uniform(0, 1, size=(n, self.n_classes))
        scores = (scores.T / np.sum(scores, axis=1)).T  # XXX softmax?

        return [
            {c: scores[i, c] for c in range(self.n_classes)} for i in range(len(unlabelled_data))
        ]


class DummyRegressionModel(RegressionModel):
    def __init__(self, *, range: tuple[float, float]):
        self.range = range
        self._rng = np.random.default_rng(0)

    def train(self, labelled_data) -> None:
        pass

    def predict(self, unlabelled_data: list[str]) -> list[float]:
        return [(inf + sup) * 0.5 for inf, sup in self.predict_interval(unlabelled_data)]

    def get_embeddings(self, data: list[str]) -> list[list[float]]:
        n = len(data)
        return self._rng.uniform(0, 1, size=(n, 3))

    def predict_interval(self, unlabelled_data: list[str]) -> list[tuple[float, float]]:
        n = len(unlabelled_data)

        boundaries = self._rng.uniform(*self.range, size=(n, 2))
        boundaries = np.sort(boundaries, axis=1)

        return [(boundaries[i, 0], boundaries[i, 1]) for i in range(len(unlabelled_data))]
