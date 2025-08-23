from abc import ABC, abstractmethod

import numpy as np

from ..models import ClassificationModel
from ..models.conformal import UncertantyPredictor


class Policy(ABC):
    @abstractmethod
    def rank(
        self, candidates: list[str], model: ClassificationModel
    ) -> list[int]:  # should not mutate self
        """Ranks all candidates based on a defined Policy.

        Args:
            candidates (list[str]): Candidates to be ranked
            model (ClassificationModel): Model to rank candidates

        Returns:
            list[int]: Ids of ranked candidates.
        """
        pass

    @abstractmethod
    def inform(self, reward: float) -> None:  # may mutate self
        pass


class EntropyPolicy(Policy):
    def rank(self, candidates: list[str], model: ClassificationModel) -> list[int]:
        probas = model.predict_proba(candidates)
        entropies = -np.sum(probas * np.log(probas + 1e-7), axis=1)
        return np.argsort(entropies)[::-1]

    def inform(self, reward: float) -> None:
        pass


class LeastConfidencePolicy(Policy):
    def rank(self, candidates: list[str], model: ClassificationModel) -> list[int]:
        probas = model.predict_proba(candidates)
        confidences = np.max(probas, axis=1)
        return np.argsort(confidences)[::-1]

    def inform(self, reward: float) -> None:
        pass


class Top2MarginPolicy(Policy):
    def rank(self, candidates: list[str], model: ClassificationModel) -> list[int]:
        probas = model.predict_proba(candidates)
        sorted_probas = np.sort(probas, axis=1)  # XXX double-check
        margins = sorted_probas[:, -1] - sorted_probas[:, -2]
        return np.argsort(margins)

    def inform(self, reward: float) -> None:
        pass


class ConformalUnsertantyPolicy(Policy):
    def rank(self, candidates: list[str], model: UncertantyPredictor) -> list[int]:
        uncert = model.predict_uncert(candidates)
        return np.argsort(uncert)[::-1]

    def inform(self, reward: float) -> None:
        pass
