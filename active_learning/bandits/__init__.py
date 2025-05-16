from abc import ABC, abstractmethod

import numpy as np


class BanditExplorer(ABC):
    @abstractmethod
    def n_levers(self) -> int:
        pass

    @abstractmethod
    def inform(self, lever: int, reward: float) -> None:
        pass

    @abstractmethod
    def select_lever(self) -> int:
        pass


class DummyBandit(BanditExplorer):
    def __init__(self, *, n_levers: int, prob_levers: list[int], rng):
        self.prob_levers = prob_levers
        self.rng: np.random.Generator = rng
        self.n_levers = n_levers

    def n_levers(self):
        return self.n_levers

    def inform(self, lever, reward):
        pass

    def select_lever(self):
        return self.rng.choice(range(self.n_levers), p=self.prob_levers)


class EpsilonGreedy(BanditExplorer):
    def __init__(self, *, n_levers: int, epsilon: float, rng):
        self.epsilon = epsilon
        self.rng = rng

        self._highest_known_payouts = np.ones(n_levers) * (-np.inf)

    def n_levers(self):
        return len(self._highest_known_payouts)

    def inform(self, lever: int, reward: float) -> None:
        self._highest_known_payouts[lever] = max(
            self._highest_known_payouts[lever], reward
        )

    def select_lever(self) -> int:
        if self.rng.random() <= self.epsilon:
            return self.rng.integers(0, self.n_levers())
        else:
            # Adapted from https://stackoverflow.com/a/42071648/4803382
            max_value = np.max(self._highest_known_payouts)
            return self.rng.choice(
                np.flatnonzero(self._highest_known_payouts == max_value)
            )


class ConformalUCB(BanditExplorer):
    def __init__(self, *, n_levers: int, reward_upper_bound: float, rng):
        self.rng = rng

        self.reward_upper_bound = reward_upper_bound
        self._payouts = [[] for _ in range(n_levers)]

    def n_levers(self):
        return len(self._payouts)

    def inform(self, lever: int, reward: float) -> None:
        self._payouts[lever].append(reward)

    def select_lever(self) -> int:
        upper_bounds = [
            (np.sum(these_payouts) + self.reward_upper_bound) / (len(these_payouts) + 1)
            for these_payouts in self._payouts
        ]

        # Adapted from https://stackoverflow.com/a/42071648/4803382
        max_value = np.max(upper_bounds)
        return self.rng.choice(np.flatnonzero(upper_bounds == max_value))
