from abc import ABC, abstractmethod
import numpy as np

from ..models import ClassificationModel
from ..models.conformal import UncertantyPredictor
from ..utils import dict_to_list
from ..bandits import BanditExplorer


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
        probas = np.array(
            [dict_to_list(preds) for preds in model.predict_proba(candidates)]
        )
        entropies = -np.sum(probas * np.log(probas + 1e-7), axis=1)
        return np.argsort(entropies)[::-1]

    def inform(self, reward: float) -> None:
        pass


class LeastConfidencePolicy(Policy):
    def rank(self, candidates: list[str], model: ClassificationModel) -> list[int]:
        probas = np.array(
            [dict_to_list(preds) for preds in model.predict_proba(candidates)]
        )
        confidences = np.max(probas, axis=1)
        return np.argsort(confidences)[::-1]

    def inform(self, reward: float) -> None:
        pass


class Top2MarginPolicy(Policy):
    def rank(self, candidates: list[str], model: ClassificationModel) -> list[int]:
        probas = np.array(
            [dict_to_list(preds) for preds in model.predict_proba(candidates)]
        )
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


# The classes below need to be adapted to return a ranking of candidates
# class KeywordPolicyCombinator(Policy):
#     def __init__(
#         self,
#         *,
#         bandit_explorer: BanditExplorer,
#         subpolicy: Policy,
#         keywords: list[str],
#     ):
#         assert bandit_explorer.n_levers() == 2

#         self.bandit_explorer = bandit_explorer
#         self.subpolicy = subpolicy
#         self.keywords = keywords

#         self._cache_rng()

#     def _cache_rng(self):
#         self._look_for_keywords = self.bandit_explorer.select_lever() == 1

#     def query(self, candidates: list[str], model: ClassificationModel):
#         if self._look_for_keywords:
#             filtered = [
#                 (i, text)
#                 for i, text in enumerate(candidates)
#                 if any(keyword in text.lower() for keyword in self.keywords)
#             ]
#         else:
#             filtered = [
#                 (i, text)
#                 for i, text in enumerate(candidates)
#                 if not any(keyword in text.lower() for keyword in self.keywords)
#             ]

#         j = self.subpolicy.query([text for _, text in filtered], model)

#         return filtered[j][0]

#     def inform(self, reward: float) -> None:
#         self.subpolicy.inform(reward)
#         self.bandit_explorer.inform(
#             {False: 0, True: 1}[self._look_for_keywords], reward
#         )  # dict lookup so that we get an error if an unexpected value shows up (e.g. because we've changed the number of levers)
#         self._cache_rng()


# class ExpectedErrorReduction(Policy):
#     def query(self, candidates: list[str], model: ClassificationModel):
#         probas = np.array([dict_to_list(preds) for preds in model.predict_proba(candidates)])
#         pass


# class ExpectedAveragePrecisionPolicy(Policy):
#     def query(self, candidates: list[str], model: ClassificationModel):
#         probas = np.array([dict_to_list(preds) for preds in model.predict_proba(candidates)])
#         pass
