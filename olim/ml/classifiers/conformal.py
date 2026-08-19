import math
from abc import abstractmethod

import numpy as np
from sklearn.model_selection import train_test_split

from . import ClassificationModel

BIG_N: float = (
    10e30  # numpy doesn't like infinity in quantiles, so we'll just use an
    # outrageously large number instead.
)


class UncertantyPredictor(ClassificationModel):
    @abstractmethod
    def predict_uncert(self, unlabelled_data: list[str]) -> np.ndarray:
        """One uncertainty score per sample; higher means a better candidate."""


class ConformalPredictor(UncertantyPredictor):
    def __init__(
        self,
        model: ClassificationModel,
        calibration_split_size: float = 0.20,
        alpha: float = 0.1,
        n_classes: int | None = None,
    ) -> None:
        self.model: ClassificationModel = model
        self.calibration_split_size: float = calibration_split_size
        # BIG_N until calibrated: an untrained predictor admits every class rather
        # than pretending to a confidence it has not earned.
        self.threshold: float = BIG_N
        self.alpha: float = alpha
        self.alpha_effective: float = alpha
        self.degenerate: bool = False
        self.n_classes: int | None = n_classes

    def _score(self, y: float | np.ndarray) -> float | np.ndarray:
        """Nonconformity of a predicted probability. Vectorised over arrays."""
        return 1 - y

    def train(
        self,
        labelled_data: list[tuple[str, int]],
        validation_data: list[tuple[str, int]] | None = None,
        skip_model_train: bool = False,
        alpha: float | None = None,
        fit_corpus: list[str] | None = None,
        **kwargs,
    ) -> None:
        alpha = alpha or self.alpha
        if validation_data is None or len(validation_data) == 0:
            train_labelled_data, cal_labelled_data = train_test_split(
                labelled_data, test_size=self.calibration_split_size, random_state=0
            )
        else:
            train_labelled_data = labelled_data
            cal_labelled_data = validation_data

        if self.n_classes is None:
            y = [i for _, i in labelled_data]
            labels = np.sort(np.unique(y))
            assert all(i == j for i, j in zip(labels, np.arange(np.max(y) + 1), strict=False)), (
                "Failed to detect classes, try setting n_classes"
            )
            self.n_classes = len(labels)
        else:
            labels = np.arange(self.n_classes)

        # Train model
        if not skip_model_train:
            self.model.train(train_labelled_data, fit_corpus=fit_corpus, **kwargs)

        # Predict probs for calibration data
        cal_unlabeled_data = [s for s, _ in cal_labelled_data]
        cal_labels = np.array([i for _, i in cal_labelled_data])
        cal_probs = np.asarray(self.model.predict_proba(cal_unlabeled_data))

        # A calibration set of n points can only certify error rates down to
        # 1/(n+1); asking for less leaves the threshold at the BIG_N sentinel, which
        # admits every class into every prediction set, flattens predict_uncert to a
        # constant and turns uncertainty sampling into random sampling. Loosen alpha
        # to the tightest level this calibration set can actually support.
        n_cal = len(cal_labels)
        alpha_floor = 1.0 / (n_cal + 1) if n_cal > 0 else 1.0
        self.alpha_effective = float(max(alpha, alpha_floor))
        self.degenerate = self.alpha_effective > alpha

        # Label-conditional thresholds — eq. (2) of Genari & Goedert (2025),
        # arXiv:2502.04372, the paper this framework implements.
        #
        # DELIBERATELY NOT USED for prediction sets: `self.threshold` below is a
        # single marginal threshold instead. That trades away the paper's per-class
        # coverage (Theorem 1) — measured on a 12%-prevalence set, the rare class
        # gets ~0.75 coverage against a 0.90 target, while the marginal figure still
        # reads 0.91 — in exchange for tighter sets and better observed behaviour on
        # the imbalanced data this is used with. Kept computed because it is cheap
        # and worth reporting; do not "fix" the unused variable by wiring it in
        # without revisiting that trade-off.
        self.cat_threshold = np.zeros(labels.shape)
        for i in range(len(labels)):
            mask_label = cal_labels == i
            scores = self._score(cal_probs[mask_label, i])
            self.cat_threshold[i] = self._conformal_quantile(scores, self.alpha_effective)

        # Calculate non-cat conditional threshold
        true_probs = cal_probs[np.arange(len(cal_labels)), cal_labels]
        scores = self._score(true_probs)
        self.threshold = self._conformal_quantile(scores, self.alpha_effective)

    @staticmethod
    def _conformal_quantile(scores: np.ndarray | float, alpha: float) -> float:
        """Split-conformal threshold: the ceil((n+1)(1-alpha))-th smallest score.

        The order statistic is used directly rather than np.quantile over the scores
        plus a BIG_N sentinel. Linear interpolation against that sentinel drags the
        result towards 1e31 for any small n, so the "infinite threshold" failure
        showed up well past the sample count where conformal coverage is achievable.
        """
        scores = np.atleast_1d(np.asarray(scores))
        n = len(scores)
        if n == 0:
            return BIG_N
        k = math.ceil((n + 1) * (1 - alpha))
        if k > n:
            return BIG_N  # cannot certify this alpha with this much calibration data
        return float(np.sort(scores)[k - 1])

    def get_embeddings(self, data: list[str]) -> list[list[float]]:
        return self.model.get_embeddings(data)

    def raw_predictions(self, unlabelled_data: list[str]) -> list[int]:
        return self.model.predict(unlabelled_data)

    def predict(self, unlabelled_data: list[str]) -> list[list[int]]:
        probas = np.asarray(self.model.predict_proba(unlabelled_data))
        preds_array = np.argmax(probas, axis=1)
        mask_uncertain = np.sum(self._score(probas) <= self.threshold, axis=1) > 1
        preds = [[int(p)] for i, p in enumerate(preds_array) if not mask_uncertain[i]]
        return preds

    def predict_proba(self, unlabelled_data: list[str]) -> np.ndarray:
        return self.model.predict_proba(unlabelled_data)

    def predict_trusted(self, unlabelled_data: list[str]) -> np.ndarray:
        """Return boolean mask: True where exactly 1 class qualifies in the prediction set."""
        probas = np.asarray(self.model.predict_proba(unlabelled_data))
        scores = 1 - probas  # nonconformity score per class
        n_passing = np.sum(scores <= self.threshold, axis=1)
        return n_passing == 1

    def predict_uncert(self, unlabelled_data: list[str]) -> np.ndarray:
        """Uncertainty score per sample — higher means a better labelling candidate.

        Eq. (4) of Genari & Goedert (2025): the *mean* nonconformity over the labels
        inside the conformal prediction set,

            S_X = (1 / |C(X)|) * sum_{y in C(X)} s(X, y)

        Averaging rather than summing keeps a wider set from scoring higher merely
        for having more terms, which would conflate set size with ambiguity. (For a
        binary label the two agree, since at most one class can clear a threshold
        below 0.5 — the difference shows up on three-way and multiple-choice labels.)

        Two additions the paper leaves open:

        * An *empty* prediction set makes eq. (4) a 0/0. Nothing fit the calibrated
          threshold, so the sample is anomalous; it takes the largest value a mean
          nonconformity can have. Summing over the empty set used to give it 0 — the
          score of the most confident possible prediction — so the entries most worth
          labelling sorted last.
        * A small margin term breaks ties. It matters most when calibration data is
          thin and the set-based score is near-constant across the whole pool.
        """
        probas = np.asarray(self.model.predict_proba(unlabelled_data))
        if probas.size == 0:
            return np.zeros(0)

        scores = self._score(probas)
        in_set = scores <= self.threshold
        n_in_set = np.sum(in_set, axis=1)
        set_sum = np.sum(np.where(in_set, scores, 0.0), axis=1)

        uncertainty = np.where(
            n_in_set == 0,
            1.0,  # empty set: maximal, see above
            set_sum / np.maximum(n_in_set, 1),
        )

        # Margin between the two best classes, 0 (decisive) .. 1 (a coin flip).
        if probas.shape[1] >= 2:
            top2 = np.sort(probas, axis=1)[:, -2:]
            margin = 1.0 - (top2[:, 1] - top2[:, 0])
        else:
            margin = np.zeros(probas.shape[0])
        uncertainty = uncertainty + 1e-3 * margin

        return np.nan_to_num(uncertainty)
