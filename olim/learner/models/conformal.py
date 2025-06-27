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
    def predict_uncert(self, unlabelled_data: list[str]) -> list[dict[int, float]]:
        pass


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
        self.threshold: list[float] | None = None
        self.alpha: float = alpha
        self.n_classes: int | None = n_classes

    def _score(self, y: int) -> float:
        return 1 - y

    def train(
        self,
        labelled_data: list[tuple[str, int]],
        validation_data: list[tuple[str, int]] | None = None,
        skip_model_train: bool = False,
        alpha: float | None = None,
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
        else:
            labels = np.arange(self.n_classes)

        # assert np.all(np.isin([i for _, i in labelled_data], labels))

        # Train model
        if not skip_model_train:
            self.model.train(train_labelled_data, **kwargs)

        # Predict probs for calibration data
        cal_unlabeled_data = [s for s, _ in cal_labelled_data]
        cal_labels = np.array([i for _, i in cal_labelled_data])
        cal_probs = self.model.predict_proba(cal_unlabeled_data)

        # Calculate cat conditional thresholds for each label
        self.cat_threshold = np.zeros(labels.shape)
        for i in range(len(labels)):
            mask_label = cal_labels == i
            scores = self._score(cal_probs[mask_label, i])
            self.cat_threshold[i] = np.quantile(np.concatenate((scores, [BIG_N])), 1 - self.alpha)

        # Calculate non-cat conditional threshold
        true_probs = cal_probs[np.arange(len(cal_labels)), cal_labels]
        scores = self._score(true_probs)
        print(scores.shape)
        self.threshold = np.quantile(np.concatenate((scores, [BIG_N])), 1 - self.alpha)

    def get_embeddings(self, data: list[str]) -> list[list[float]]:
        return self.model.get_embeddings(data)

    def raw_predictions(self, unlabelled_data: list[str]) -> list[int]:
        return self.model.predict(unlabelled_data)

    def predict(self, unlabelled_data: list[str]) -> list[list[int]]:
        probas = self.model.predict_proba(unlabelled_data)
        # preds = [
        #     [i for i, t in enumerate(self.threshold) if self._score(prob[i]) <= t]
        #     for prob in probas
        # ]
        preds_array = np.argmax(probas, axis=1)
        mask_uncertain = np.sum(self._score(probas) <= self.threshold, axis=1) > 1
        preds = [[int(p)] for i, p in enumerate(preds_array) if not mask_uncertain[i]]

        # preds = [
        #     [i for i in range(self.n_classes) if self._score(prob[i]) <= self.threshold]
        #     for prob in probas
        # ]
        # for i in range(len(preds)):
        #     if len(preds[i]) == 0:
        #         preds[i] = [np.argmax(probas[i, :])]
        return preds

    def predict_proba(self, unlabelled_data: list[str]) -> list[dict[int, float]]:
        return self.model.predict_proba(unlabelled_data)

    def predict_uncert(self, unlabelled_data: list[str]) -> list[dict[int, float]]:
        probas = self.model.predict_proba(unlabelled_data)
        score = np.array(
            [
                np.sum(
                    [
                        self._score(prob[i])
                        for i in range(self.n_classes)
                        if self._score(prob[i]) <= self.threshold
                    ]
                )
                for prob in probas
            ]
        )
        # score = np.array(
        #     [
        #         np.mean(
        #             [
        #                 self._score(prob[i])
        #                 for i, t in enumerate(self.threshold)
        #                 if self._score(prob[i]) <= t
        #             ]
        #         )
        #         for prob in probas
        #     ]
        # )
        return np.nan_to_num(score)
