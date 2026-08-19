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
from sklearn.utils.class_weight import compute_sample_weight
from xgboost import XGBClassifier

from . import ClassificationModel, RegressionModel


class TfidfSklearnClassificationModel(ClassificationModel):
    """TF-IDF + sklearn-style classifier with a fixed global class space.

    ``predict_proba`` always returns ``n_classes`` columns indexed by global class
    id, even when a class is missing from the training split. Everything
    downstream (conformal scoring, prediction storage, the label encoder) indexes
    probabilities positionally, so a narrower matrix would silently attribute one
    class's probability to another.
    """

    def __init__(
        self,
        *args,
        ngram_range: tuple[int, int] = (1, 2),
        n_classes: int | None = None,
        sublinear_tf: bool = True,
        strip_accents: str | None = "unicode",
        min_df: int | float = 1,
        max_features: int | None = 50000,
        balance_classes: bool = True,
        **kwargs,
    ) -> None:
        self.n_classes = n_classes
        self.balance_classes = balance_classes
        self.embedding = TfidfVectorizer(
            ngram_range=ngram_range,
            sublinear_tf=sublinear_tf,
            strip_accents=strip_accents,
            min_df=min_df,  # type: ignore[arg-type]  # sklearn accepts a float fraction
            max_features=max_features,
        )
        self.model = self._create_model(*args, **kwargs)
        # Global class ids seen during training, in the order the estimator uses.
        self._fit_classes: np.ndarray = np.array([], dtype=int)
        # Set when the training data holds a single class and no estimator was fit.
        self._single_class: int | None = None

    @abstractmethod
    def _create_model(self, *args, **kwargs) -> Any:  # noqa: ANN401
        pass

    def _supports_sample_weight(self) -> bool:
        """Whether balancing is applied through fit(sample_weight=...).

        Estimators that take ``class_weight`` in their constructor handle it there
        instead — see the subclasses.
        """
        return True

    def train(
        self,
        labelled_data: list[tuple[str, int]],
        fit_corpus: list[str] | None = None,
    ) -> None:
        """Fit the vectorizer and the estimator.

        Args:
            labelled_data: (text, global_class_id) pairs
            fit_corpus: Texts to fit the vectorizer on. Defaults to the training
                texts, but at low data that vocabulary is far too small for the
                validation and pool documents — pass the wider unlabelled corpus.
        """
        unlabelled_data = [text for text, label in labelled_data]
        labels = np.asarray([label for text, label in labelled_data])

        available_labels = np.unique(labels)
        if self.n_classes is None:
            self.n_classes = int(available_labels.max()) + 1

        self._fit_classes = available_labels
        self._single_class = None

        if len(available_labels) < 2:
            # Every label so far is the same answer. XGBoost and LogisticRegression
            # both raise on this, which used to fail the whole training round — and
            # it is the normal state early in a rare-label campaign, exactly when
            # the loop most needs to keep running. Fit the vectoriser and stand in a
            # constant predictor until the first counter-example arrives.
            self._single_class = int(available_labels[0])
            self.embedding.fit(fit_corpus if fit_corpus else unlabelled_data)
            return

        # Map global class ids to the contiguous 0..k-1 range some estimators
        # (XGBoost) require, keeping the inverse so predictions come back global.
        local_by_global = {int(g): i for i, g in enumerate(available_labels)}
        encoded_labels = np.array([local_by_global[int(y)] for y in labels])

        self.embedding.fit(fit_corpus if fit_corpus else unlabelled_data)

        feature_matrix = self.embedding.transform(unlabelled_data)

        fit_kwargs: dict[str, Any] = {}
        if self.balance_classes and self._supports_sample_weight() and len(available_labels) > 1:
            fit_kwargs["sample_weight"] = compute_sample_weight("balanced", encoded_labels)
        self.model.fit(feature_matrix, encoded_labels, **fit_kwargs)

    def get_embeddings(self, data: list[str]) -> list[list[float]]:
        return self.embedding.transform(data)

    def predict(self, unlabelled_data: list[str]) -> list[int]:
        if len(unlabelled_data) == 0:
            return []
        probas = self.predict_proba(unlabelled_data)
        return [int(i) for i in np.argmax(probas, axis=1)]

    def predict_proba(self, unlabelled_data: list[str]) -> np.ndarray:
        """Return an (n_samples, n_classes) matrix indexed by global class id."""
        n_classes = self.n_classes or (len(self._fit_classes) or 1)
        if len(unlabelled_data) == 0:
            return np.zeros((0, n_classes))

        if self._single_class is not None:
            probas = np.zeros((len(unlabelled_data), n_classes))
            probas[:, self._single_class] = 1.0
            return probas

        feature_matrix = self.embedding.transform(unlabelled_data)
        local_probas = np.asarray(self.model.predict_proba(feature_matrix))

        # Estimator columns follow model.classes_ (local ids); scatter them back
        # into the global class space so column i always means class i.
        probas = np.zeros((local_probas.shape[0], n_classes))
        local_classes = np.asarray(
            getattr(self.model, "classes_", np.arange(local_probas.shape[1]))
        )
        for col, local_id in enumerate(local_classes):
            if col >= local_probas.shape[1]:
                break
            global_id = int(self._fit_classes[int(local_id)])
            if 0 <= global_id < n_classes:
                probas[:, global_id] = local_probas[:, col]
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
        kwargs.setdefault("class_weight", "balanced" if self.balance_classes else None)
        return LogisticRegression(*args, **kwargs, random_state=0)

    def _supports_sample_weight(self) -> bool:
        return False  # handled by class_weight


class TfidfDecisionTreeClassifier(TfidfSklearnClassificationModel):
    def _create_model(self, *args, **kwargs) -> Any:  # noqa: ANN401
        kwargs.setdefault("class_weight", "balanced" if self.balance_classes else None)
        return DecisionTreeClassifier(*args, **kwargs, random_state=0)

    def _supports_sample_weight(self) -> bool:
        return False  # handled by class_weight


class TfidfXGBoostClassifier(TfidfSklearnClassificationModel):
    def _create_model(self, *args, **kwargs) -> Any:  # noqa: ANN401
        return XGBClassifier(*args, **kwargs, random_state=0)


class TfidfLightGBMClassifier(TfidfSklearnClassificationModel):
    def _create_model(self, *args, **kwargs) -> Any:  # noqa: ANN401
        kwargs.setdefault("verbose", -1)
        # Stock LightGBM will not split a node below 20 samples, so at active
        # learning scale (a few dozen labels for the first rounds) it returns a
        # constant probability for every entry — a useless model, and a flat
        # uncertainty ranking that reduces entry selection to random sampling.
        kwargs.setdefault("min_child_samples", 2)
        kwargs.setdefault("min_split_gain", 0.0)
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
