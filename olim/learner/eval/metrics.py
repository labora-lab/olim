from abc import ABC, abstractmethod

import numpy as np
from sklearn.metrics import accuracy_score, precision_score, recall_score, roc_auc_score

from ..models import ClassificationModel
from ..utils import dict_to_list


class ProbabilisticMetric(ABC):
    @abstractmethod
    def __call__(self, y_true: list[dict[int, float]], y_pred: list[int]) -> float:
        pass


class ConcreteMetric(ABC):
    @abstractmethod
    def __call__(self, y_true: list[int], y_pred: list[int]) -> float:
        pass


class Auc(ProbabilisticMetric):
    def __call__(self, y_true: list[dict[int, float]], y_pred: list[int]) -> float:
        return roc_auc_score(
            np.asarray(y_true),
            [dict_to_list(preds) for preds in y_pred],
            multi_class="ovr",
        )  # FIXME


class Accuracy(ConcreteMetric):
    def __call__(self, y_true: list[int], y_pred: list[int]) -> float:
        return accuracy_score(y_true, y_pred)


class Precision(ConcreteMetric):
    def __call__(self, y_true: list[int], y_pred: list[int]) -> float:
        return precision_score(
            y_true, y_pred, zero_division=1
        )  # TODO switch to `zero_division=np.nan`


class Recall(ConcreteMetric):
    def __call__(self, y_true: list[int], y_pred: list[int]) -> float:
        return recall_score(
            y_true, y_pred, zero_division=1
        )  # TODO switch to `zero_division=np.nan`


Metrics = list[ProbabilisticMetric | ConcreteMetric]


def evaluate_metrics(
    metrics: Metrics, model: ClassificationModel, labelled_data: list[tuple[str, int]]
) -> dict[str, float]:
    unlabelled_data = [text for text, label in labelled_data]
    y_true = [label for text, label in labelled_data]

    out = {}
    for metric in metrics:
        if isinstance(metric, ProbabilisticMetric):
            value = metric(y_true, model.predict_proba(unlabelled_data))
        elif isinstance(metric, ConcreteMetric):
            value = metric(y_true, model.predict(unlabelled_data))
        else:
            raise TypeError()
        out[type(metric).__name__] = value
    return out
