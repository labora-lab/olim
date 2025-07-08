import json
import pickle
import warnings
from collections.abc import Callable
from pathlib import Path
from statistics import multimode
from threading import Lock
from typing import TypeAlias, Callable

import numpy as np
import numpy.typing as npt
from sklearn.preprocessing import LabelEncoder
from sklearn.cluster import KMeans
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    pairwise_distances_argmin_min as dist_argmin,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.preprocessing import LabelEncoder

from .active.policies import ConformalUnsertantyPolicy, Policy
from .bandits import BanditExplorer, DummyBandit
from .eval.metrics import accuracy, precision, recall, specificity, auc_roc
from .models import ClassificationModel, DummyClassificationModel
from .models.conformal import ConformalPredictor
from .settings import CLASSIFICATION_MODEL, SKIP_AL, UNCERTAIN_PERC
from .utils import SlotSet, sanitize_data

if CLASSIFICATION_MODEL == "TfidfXGBoostClassifier":
    from .models.tfidf_sklearn import TfidfXGBoostClassifier
elif CLASSIFICATION_MODEL == "DebertaV3Wrapper":
    from .models.keras_classifiers import DebertaV3Wrapper

VALIDATE_PROB = 0.4
USE_BANDIT = False

# Define type aliases
LabelValue = str
EntryId = int | str
FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]
ConfidenceInterval = tuple[float, float]
MetricResult: TypeAlias = float | dict[str, float] | list[float]
MetricWithCI: TypeAlias = tuple[
    MetricResult,
    ConfidenceInterval | dict[str, ConfidenceInterval] | list[ConfidenceInterval],
]


class ActiveLearningBackend:
    n_kickstart: int
    label_values: list[str]

    subsample_size: list[int]
    recall_frequency: int
    # [N, n, k] entries to cache based policy
    # N entries to be ranked, embeeded or predicted (optional)
    # n entries to be clustered, this is also our cache size
    # k cluster to select best entries
    # N > n > k
    _original_dataset: dict[EntryId, str]
    _unlabelled_dataset: SlotSet[EntryId]
    # _train_dataset: dict[EntryId, tuple[str, int]]
    # _val_dataset: dict[EntryId, tuple[str, int]]
    # ([entry, label_value, user_id, timestamp], is_validation, true_label_value)
    _dataset: dict[EntryId, tuple[list[tuple[str, int, int, float]], bool, int]]
    _cached_subsample: list[EntryId]
    _given_nexts: list[EntryId]

    _label_value_encoder: LabelEncoder
    _bandit_explorer: BanditExplorer
    _policy: Policy
    _model: ClassificationModel
    _rng: np.random.Generator

    _training: bool
    _retrain: bool
    _data_lock: Lock
    _cache_lock: Lock
    _validate: bool

    def __init__(
        self,
        original_dataset: dict[EntryId, str],
        label_values: list[str],
        *,
        # model_factory: Callable[[], ClassificationModel],
        policy: Policy | None = None,
        initial_label_value_dataset: dict[EntryId, LabelValue] | None = None,
        n_kickstart: int = 10,
        subsample_size: list[int] | None = None,
        unbiased_evaluation: bool = False,
        entry_ids_to_remove: set[EntryId] | None = None,
        precomputed_original_dataset_keys: SlotSet[EntryId] | None = None,
        rng: np.random.Generator,
        save_path: Path | str | None = None,
    ) -> None:
        if not (isinstance(n_kickstart, int) and n_kickstart >= 1):
            raise TypeError("`n_kickstart` must be an `int` >= 1")

        if policy is None:
            policy = ConformalUnsertantyPolicy()
        if subsample_size is None:
            subsample_size = [5_000, 1_000, 20]

        self.messages = []
        self.msg_lock = Lock()
        self.metrics_strs = []
        self.save_path = save_path

        self.n_kickstart = n_kickstart
        self.subsample_size = subsample_size
        self.unbiased_evaluation = unbiased_evaluation

        self._original_dataset = original_dataset
        self._dataset = {}

        self.label_values = label_values
        self._label_value_encoder = LabelEncoder()
        self._label_value_encoder.fit(label_values)

        if precomputed_original_dataset_keys is None:
            self._unlabelled_dataset = SlotSet(original_dataset.keys())
        else:
            self._unlabelled_dataset = precomputed_original_dataset_keys.shallow_copy()
        if entry_ids_to_remove is not None:
            for entry_id in entry_ids_to_remove:
                self._unlabelled_dataset.remove(entry_id)
        if initial_label_value_dataset is not None:
            for entry_id, label_value in initial_label_value_dataset.items():
                # TODO: Keep track of it
                self._dataset[entry_id] = (
                    [(original_dataset[entry_id], self._encode(label_value), -1, -1)],
                    False,
                    self._encode(label_value),
                )
                self._unlabelled_dataset.remove(entry_id)

        self._rng = rng

        # Start cache ranromly while we dont have a trained model
        cached_subsample_is = self._rng.choice(
            np.arange(len(self._unlabelled_dataset)),
            min(self.subsample_size[-2], len(self._unlabelled_dataset)),
            replace=False,
        )
        self._cached_subsample = [
            self._unlabelled_dataset[i] for i in cached_subsample_is
        ]
        self._given_nexts = []
        self._validate = False

        # self._bandit_explorer = EpsilonGreedy(n_levers=2, epsilon=0.1, rng=self._rng)        self._data_lock = Lock()
        self._cache_lock = Lock()
        # self._bandit_explorer = ConformalUCB(
        #     n_levers=2, reward_upper_bound=1, rng=self._rng
        # )
        self._bandit_explorer = DummyBandit(
            n_levers=len(label_values), prob_levers=[0.8, 0.2], rng=self._rng
        )
        self._policy = policy

        self._data_lock = Lock()
        self._cache_lock = Lock()
        self._model = DummyClassificationModel(n_classes=len(self.label_values))

        # If we have enought entries we start training
        self._training = False
        self._retrain = False
        self._count_since_last_train = 0

    def _encode(self, label_value: LabelValue | list[LabelValue]) -> int | list[int]:
        if isinstance(label_value, list | np.ndarray):
            return self._label_value_encoder.transform(label_value).tolist()
        else:
            return self._label_value_encoder.transform([label_value])[0]

    def _decode(
        self, encoded_label_value: int | list[int] | np.ndarray
    ) -> str | list[str]:
        if isinstance(encoded_label_value, list | np.ndarray):
            return self._label_value_encoder.inverse_transform(
                encoded_label_value
            ).tolist()
        else:
            return self._label_value_encoder.inverse_transform([encoded_label_value])[0]

    def _cache_whether_to_validate(self) -> None:
        self._validate = self._bandit_explorer.select_lever() == 1

    def _train(self) -> None:
        self.message("Starting training.")
        # Load data
        with self._data_lock:
            unlabelled_ids = np.array(self._unlabelled_dataset)
            unlabelled = [
                self._original_dataset[entry_id] for entry_id in unlabelled_ids
            ]
            unlabelled_dict = {
                entry_id: self._original_dataset[entry_id]
                for entry_id in unlabelled_ids
            }
            labelled = [
                (self._original_dataset[entry_id], label_value)
                for entry_id, label_value in self._train_dataset.items()
            ]
            validation = [
                (self._original_dataset[entry_id], label_value)
                for entry_id, label_value in self._val_dataset.items()
            ]
            rng = np.random.default_rng(seed=self._rng.integers(np.iinfo(int).max))
            # del self._model
            # self._model = DummyClassificationModel(n_classes=len(self.label_values))
            with self._cache_lock:
                self._count_since_last_train = 0

        print(len(labelled) + len(validation))
        if len(labelled) + len(validation) < self.n_kickstart:
            self.message("Not enough label values, skipping training.")
            return None

        # Train new model
        if CLASSIFICATION_MODEL == "TfidfXGBoostClassifier":
            class_model = TfidfXGBoostClassifier(n_classes=len(self.label_values))
        elif CLASSIFICATION_MODEL == "DebertaV3Wrapper":
            class_model = DebertaV3Wrapper(
                n_classes=len(self.label_values),
                model="deberta_v3_base_en",
                verbose=0,
            )
        else:
            # Fallback to dummy model if no specific model is configured
            class_model = DummyClassificationModel(n_classes=len(self.label_values))

        model = ConformalPredictor(
            model=class_model,
            alpha=0.1,
            n_classes=len(self.label_values),
        )
        self.message("Instanced model")
        model.train(labelled, validation)  # , epochs=3)
        self.message("Done training")

        new_cache = None
        if not SKIP_AL:
            self.message("Hanking for AL")
            if len(self.subsample_size) == 3:
                ids = rng.integers(len(unlabelled), size=(self.subsample_size[-3]))
                candidates_ids = unlabelled_ids[ids]
                candidates_txt = [unlabelled[i] for i in ids]
            else:
                candidates_ids = unlabelled_ids
                candidates_txt = unlabelled

            # Get k most uncertain
            sorted_ids = candidates_ids[self._policy.rank(candidates_txt, model)][
                : int(self.subsample_size[-2])
            ]
            sorted_ids = np.concatenate(
                (
                    sorted_ids[: int(self.subsample_size[-2] * UNCERTAIN_PERC)],
                    sorted_ids[-int(self.subsample_size[-2] * (1 - UNCERTAIN_PERC)) :],
                )
            )
            self.message("Done hanking")

            # Cluster in n, and get cosest to each centroid to be highest priority on cache
            to_cluster = [unlabelled_dict[entry_id] for entry_id in sorted_ids]
            to_cluster_emb = model.get_embeddings(to_cluster)
            kmean = KMeans(self.subsample_size[-1], n_init="auto").fit(to_cluster_emb)

            best_ids = np.unique(
                np.array(
                    [
                        sorted_ids[i]
                        for i in dist_argmin(kmean.cluster_centers_, to_cluster_emb)[0]
                    ]
                )
            )

            # TODO: recall_prob to solve untrusted label_values
            other_ids = sorted_ids[~np.isin(sorted_ids, best_ids)]
            rng.shuffle(best_ids)
            rng.shuffle(other_ids)

            new_cache = np.concatenate((best_ids, other_ids))
            if isinstance(next(iter(self._original_dataset)), int):
                new_cache = (
                    new_cache[np.isin(new_cache, self._unlabelled_dataset.array)]
                    .astype(int)
                    .tolist()
                )
            else:
                new_cache = new_cache[
                    np.isin(new_cache, self._unlabelled_dataset.array)
                ].tolist()

        # Store data and do flow control
        with self._cache_lock:
            with self._data_lock:
                if not SKIP_AL and new_cache is not None:
                    self._previous_cache_top = self._cached_subsample[0]
                    self._cached_subsample = new_cache
                self._model = model
                retrain = self._retrain
                self._retrain = False
                if not retrain:
                    self._training = False

        self.metrics_strs = ["Last trained model:"]
        self.metrics_strs.append(f"n label_valued: {len(labelled) + len(validation)}")
        # Count items per label_value in training and validation sets
        train_label_value_counts = {}
        val_label_value_counts = {}

        for _, encoded_label in labelled:
            label_value = self._decode(encoded_label)
            train_label_value_counts[label_value] = (
                train_label_value_counts.get(label_value, 0) + 1
            )

        for _, encoded_label in validation:
            label_value = self._decode(encoded_label)
            val_label_value_counts[label_value] = (
                val_label_value_counts.get(label_value, 0) + 1
            )

        # Create summary strings for each label_value
        for label_value in self.label_values:
            train_count = train_label_value_counts.get(label_value, 0)
            val_count = val_label_value_counts.get(label_value, 0)
            self.metrics_strs.append(
                f"label_value {label_value} - train/val: {train_count}/{val_count}"
            )

        # AUC-ROC Overall
        _, auc_ci = self.metric_with_confidence(
            auc_roc, alpha=0.05
        )
        lower, upper = auc_ci
        self.metrics_strs.append(
            rf"AUC_ROC: \({(lower + upper) / 2:.2f} \pm {(upper - lower) / 2:.2f}\)"
        )

        # Accuracy
        _, acc_ci = self.metric_with_confidence(accuracy, alpha=0.05)
        lower, upper = acc_ci
        self.metrics_strs.append(
            rf"Accuracy: \({(lower + upper) / 2:.2f} \pm {(upper - lower) / 2:.2f}\)"
        )

        # Precision, Recall, and Specificity
        if len(self.label_values) == 2:
            # Binary classification - report for positive class
            target_value = self._encode(self.label_values[1])

            # Precision
            _, prec_ci = self.metric_with_confidence(
                precision, alpha=0.05, target=target_value
            )
            lower, upper = prec_ci
            self.metrics_strs.append(
                rf"Precision: \({(lower + upper) / 2:.2f} \pm {(upper - lower) / 2:.2f}\)"
            )

            # Recall
            _, rec_ci = self.metric_with_confidence(
                recall, alpha=0.05, target=target_value
            )
            lower, upper = rec_ci
            self.metrics_strs.append(
                rf"Recall: \({(lower + upper) / 2:.2f} \pm {(upper - lower) / 2:.2f}\)"
            )
            _, spec_ci = self.metric_with_confidence(
                specificity, alpha=0.05, target=target_value
            )
            lower, upper = spec_ci
            self.metrics_strs.append(
                rf"Specificity: \({(lower + upper) / 2:.2f} \pm {(upper - lower) / 2:.2f}\)"
            )
        else:
            # Multiclass classification - report per class
            for label_value_name in self.label_values:
                target_value = self._encode(label_value_name)
                # Precision
                _, prec_ci = self.metric_with_confidence(
                    precision, alpha=0.05, target=target_value
                )
                lower, upper = prec_ci
                self.metrics_strs.append(
                    rf"Precision ({label_value_name}): "
                    rf"\({(lower + upper) / 2:.2f} \pm {(upper - lower) / 2:.2f}\)"
                )

                # Recall
                _, rec_ci = self.metric_with_confidence(
                    recall, alpha=0.05, target=target_value
                )
                lower, upper = rec_ci
                self.metrics_strs.append(
                    rf"Recall ({label_value_name}): "
                    rf"\({(lower + upper) / 2:.2f} \pm {(upper - lower) / 2:.2f}\)"
                )

                # Specificity
                _, spec_ci = self.metric_with_confidence(
                    specificity, alpha=0.05, target=target_value
                )
                lower, upper = spec_ci
                self.metrics_strs.append(
                    rf"Specificity ({label_value_name}): \({(lower + upper) / 2:.2f} \pm {(upper - lower) / 2:.2f}\)"
                )
        self.metrics_strs.append(rf"Conformal threshold: \({model.threshold}\)")
        conf_cov = self.peek_predictions(alpha=0.05) * 100
        self.metrics_strs.append(rf"Conformal coverage: \({conf_cov:.1f} \%\)")

        for m in self.metrics_strs:
            self.message(m)

        if self.save_path is not None:
            self.save(self.save_path)
            self.message("Saved Learner")

        if retrain:
            self._train()

    @property
    def _train_dataset(self) -> dict[EntryId, int]:
        return {
            label_value_id: entry[2]
            for label_value_id, entry in self._dataset.items()
            if not entry[1] and entry[2] != -1
        }

    @property
    def _val_dataset(self) -> dict[EntryId, int]:
        return {
            label_value_id: entry[2]
            for label_value_id, entry in self._dataset.items()
            if entry[1] and entry[2] != -1
        }

    def message(self, msg) -> None:
        print(msg)
        with self.msg_lock:
            self.messages.append(msg)

    def update_trustness(self, entry_id: EntryId) -> None:
        # Updates trustness following data structures.
        label_values = [
            label_value for label_value, *_ in enumerate(self._dataset[entry_id][0])
        ]
        modes = multimode(label_values)
        if len(modes) == 1:
            # We have a single mode, we can trust this entry
            self._dataset[entry_id][2] = modes[0]
        else:
            # We have multiple modes, we cannot trust this entry
            self._dataset[entry_id][2] = -1

    # TODO: Verify if adding timestamp and user breaks this.int,
    def sync_labelling(self, labelled_data: dict[EntryId, LabelValue]) -> None:
        with self._data_lock:
            for entry_id, label_value in labelled_data.items():
                # We add everything new to self._train_dataset because manually
                # labelled data can be biased.
                # Verify if entry in
                # false is_validate
                if entry_id not in self._dataset:
                    self._dataset[entry_id] = (
                        [
                            (
                                self._original_dataset[entry_id],
                                self._encode(label_value),
                                -1,  # user_id
                                -1,
                            ),  # timestamp
                        ],
                        False,
                        self._encode(label_value),
                    )
                    self._unlabelled_dataset.remove(entry_id)
                    self._count_since_last_train += 1

        # FIXME, Recalculate bandit rewards?!?!?!?!

    def submit_labelling(
        self,
        entry_id: EntryId,
        label_value: LabelValue,
        user_id: int,
        timestamp: float,
        check_given: bool = True,
    ) -> None:
        if not isinstance(label_value, LabelValue):
            raise TypeError("`label_value` must be a `LabelValue`")

        if check_given:
            assert entry_id in self._given_nexts, "submitted an unexpected label_value"
        # inf_auc_before, _ = self.peek_auc_roc_ovr(alpha=0.1)

        with self._data_lock:
            # Overwrite _validate if we are not using bandit
            if not USE_BANDIT:
                rand = self._rng.uniform()
                current_label_value = self._encode(label_value)

                # Calculate class distribution in current validation dataset
                val_label_values = list(self._val_dataset.values())
                if len(val_label_values) > 0:
                    # Count occurrences of current label_value in validation set
                    current_label_value_count = sum(
                        1
                        for label_value in val_label_values
                        if label_value == current_label_value
                    )

                    if current_label_value_count == 0:
                        # Current label_value has no representation in validation set
                        # Use maximum probability to encourage adding it
                        prob = min(1.0, len(self.label_values) * VALIDATE_PROB)
                    else:
                        # Current label_value proportion in validation set
                        current_label_value_proportion = (
                            current_label_value_count / len(val_label_values)
                        )

                        # Dynamic prob: (n_classes/(n_classes-1)) * (1 - proportion) * VALIDATE_PROB
                        # This gives low prob for overrepresented, high prob for underrepresented
                        prob = (
                            (len(self.label_values) / (len(self.label_values) - 1))
                            * (1 - current_label_value_proportion)
                            * VALIDATE_PROB
                        )
                else:
                    # No validation data yet, use base probability
                    prob = VALIDATE_PROB
                print(label_value, prob)
                self._validate = rand < prob

            # TODO: Test this.
            if entry_id not in self._dataset:
                self._dataset[entry_id] = (
                    [
                        (
                            self._original_dataset[entry_id],
                            self._encode(label_value),
                            user_id,
                            timestamp,
                        ),
                    ],
                    self._validate,
                    self._encode(label_value),
                )
            else:
                self._dataset[entry_id][0].append(
                    (
                        self._original_dataset[entry_id],
                        self._encode(label_value),
                        user_id,
                        timestamp,
                    )
                )
                self.update_trustness(entry_id)

            if entry_id in self._unlabelled_dataset:
                self.message(f"removing from unlabel_valued: {entry_id}")
                self._unlabelled_dataset.remove(entry_id)

        # self.message(
        #     f"dataset: {len(self._train_dataset)}, validation: {len(self._val_dataset)}"
        # )

        self.message(f"dataset: {len(self._dataset)}")

        # FIXME: this auc_roc will not change between training sessions, this might break the bandit
        # inf_auc_after, _ = self.peek_auc_roc_ovr(alpha=0.1)
        # reward = inf_auc_after - inf_auc_before
        # with self._data_lock:
        #     self._bandit_explorer.inform(
        #         {True: 1, False: 0}[self._validate], reward
        #     )  # dict lookup so that we get an error if an unexpected value shows up (e.g. because we've changed the number of levers)
        #     self._policy.inform(reward)

        # Update cached_subsample and validate
        with self._cache_lock:
            if len(self._cached_subsample) >= 1:  # FIXME: Better treatment for this
                self._cached_subsample = self._cached_subsample[1:]
            self._count_since_last_train += 1
        self._cache_whether_to_validate()

    def peek_predictions(self, *, alpha: float) -> float:
        with self._data_lock:
            model = self._model
            unlabeled_data = self._unlabelled_dataset
        if len(self.subsample_size) == 3:
            ids = self._rng.integers(
                len(unlabeled_data), size=(self.subsample_size[-3])
            )
            unlabeled_data = [self._original_dataset[unlabeled_data[i]] for i in ids]
        preds = model.predict(unlabeled_data)
        return np.mean([len(pred) in [0, 1] for pred in preds])

    def metric_with_confidence(
        self,
        metric_fn: Callable[..., MetricResult],
        alpha: float = 0.05,
        n_bootstrap: int = 1000,
        **kwargs,
    ) -> MetricWithCI:
        """
        Compute metric with bootstrap confidence intervals (sequential).

        Args:
            metric_fn: Static method that computes a metric
            alpha: Confidence level
            n_bootstrap: Number of bootstrap samples
            **kwargs: Additional arguments for metric_fn

        Returns:
            Tuple of (original metric result, confidence interval(s))
        """
        with self._data_lock:
            val_dataset = self._val_dataset
            model = self._model

        # Extract texts and label_values
        n = len(val_dataset)
        if n == 0:
            return 0.0, (0.0, 1.0)

        texts = list(val_dataset.keys())
        label_values = np.array(list(val_dataset.values()))

        # Get predictions and probabilities
        preds = np.array(model.raw_predictions(texts))
        try:
            label_proba = model.predict_proba(texts)
        except AttributeError:
            label_proba = None

        # Compute original metric
        original = metric_fn(label_values, preds, label_proba, **kwargs)

        # Prepare storage based on return type
        match original:
            case float():
                bootstrap_vals = np.zeros(n_bootstrap)
                return_type = "float"
            case dict() if all(isinstance(v, float) for v in original.values()):
                keys = list(original.keys())
                bootstrap_vals = {k: np.zeros(n_bootstrap) for k in keys}
                return_type = "dict"
            case list() if all(isinstance(v, float) for v in original):
                n_metrics = len(original)
                bootstrap_vals = [np.zeros(n_bootstrap) for _ in range(n_metrics)]
                return_type = "list"
            case _:
                raise TypeError(f"Unsupported metric return type: {type(original)}")

        # Bootstrap resampling (sequential)
        rng = np.random.default_rng()
        indices = np.arange(n)

        for i in range(n_bootstrap):
            # Resample with replacement
            sample_idx = rng.choice(indices, size=n, replace=True)
            sample_texts = [texts[j] for j in sample_idx]
            sample_label_values = label_values[sample_idx]
            sample_preds = preds[sample_idx]

            # Get probabilities for resampled data if needed
            sample_label_proba = label_proba[sample_idx] if label_proba is not None else None
            
            # Compute metric on resampled data
            result = metric_fn(
                sample_label_values, sample_preds, sample_label_proba, **kwargs
            )

            # Store result based on type
            match return_type:
                case "float":
                    bootstrap_vals[i] = result
                case "dict":
                    for k in keys:
                        bootstrap_vals[k][i] = result[k]
                case "list":
                    for j, val in enumerate(result):
                        bootstrap_vals[j][i] = val

        # Compute confidence intervals
        percentiles = (100 * alpha / 2, 100 * (1 - alpha / 2))

        match return_type:
            case "float":
                ci = tuple(np.percentile(bootstrap_vals, percentiles))
            case "dict":
                ci = {
                    k: tuple(np.percentile(vals, percentiles))
                    for k, vals in bootstrap_vals.items()
                }
            case "list":
                ci = [
                    tuple(np.percentile(vals, percentiles)) for vals in bootstrap_vals
                ]

        return original, ci


    def export_preditictions(
        self,
        entry_ids: list[EntryId] | None = None,
        alpha: float = 0.95,
    ) -> dict[EntryId, list[LabelValue]]:
        if isinstance(self._model, DummyClassificationModel):
            raise ValueError(
                "Trained model not available, please add more label values to trigger a model training."
            )
        with self._data_lock:
            unlabelled_ids = entry_ids or np.array(self._unlabelled_dataset)
            unlabelled = [
                self._original_dataset[entry_id] for entry_id in unlabelled_ids
            ]
            train_dataset = self._train_dataset
            labelled = [
                (entry, label_value)
                for entry, label_value in train_dataset.values()  # type: ignore
            ]
            labelled_data = [
                (entry_id, entry[-1]) for entry_id, entry in self._dataset.items()
            ]
            validation_dataset = self._val_dataset
            validation = [
                (entry, label_value)
                for entry, label_value in validation_dataset.values()
            ]
        self._model.train(labelled, validation, skip_model_train=True, alpha=alpha)

        decode = {
            self._encode(label_value): label_value for label_value in self.label_values
        }

        data = {
            entry_id: [decode[p] for p in pred]
            for entry_id, pred in zip(
                unlabelled_ids, self._model.predict(unlabelled), strict=False
            )
        }
        for entry_id, labeling in labelled_data:
            data[entry_id] = [self._decode(labeling)]

        return data

    def save(self, path: str | Path | None = None) -> None:
        path = path or self.save_path
        path = Path(path)
        if not path.is_dir():
            path.mkdir()
        with self._data_lock:
            with open(path / "fields.json", "w") as file:
                json.dump(
                    sanitize_data(
                        {
                            "messages": self.messages,
                            "n_kickstart": self.n_kickstart,
                            "subsample_size": self.subsample_size,
                            "unbiased_evaluation": self.unbiased_evaluation,
                            "_dataset": self._dataset,
                            "label_values": self.label_values,
                            "_cached_subsample": self._cached_subsample,
                            "_validate": bool(self._validate),
                            "_given_nexts": self._given_nexts,
                        }
                    ),
                    file,
                )

            with open(path / "bandit_explorer.pickle", "wb") as file:
                pickle.dump(self._bandit_explorer, file)
            with open(path / "label_value_encoder.pickle", "wb") as file:
                pickle.dump(self._label_value_encoder, file)
            with open(path / "policy.pickle", "wb") as file:
                pickle.dump(self._policy, file)
            with open(path / "model.pickle", "wb") as file:
                pickle.dump(self._model, file)

    @classmethod
    def load(
        cls,
        path: str | Path,
        original_dataset: dict[EntryId, str],
        *,
        precomputed_original_dataset_keys: SlotSet[EntryId] | None = None,
        rng: np.random.Generator,
    ) -> "ActiveLearningBackend":
        path = Path(path)

        with open(path / "fields.json") as file:
            data = json.load(file)
        with open(path / "policy.pickle", "rb") as file:
            policy = pickle.load(file)

        if isinstance(next(iter(original_dataset.keys())), int):
            data["_dataset"] = {int(k): v for k, v in data["_dataset"].items()}

        # TODO: Remove this backward compatibility in next major version
        # Handle transition from old 'labels' key to new 'label_values' key
        if "labels" in data and "label_values" not in data:
            data["label_values"] = data["labels"]

        out = cls(
            original_dataset,
            label_values=data["label_values"],
            policy=policy,
            n_kickstart=data["n_kickstart"],
            subsample_size=data["subsample_size"],
            unbiased_evaluation=data["unbiased_evaluation"],
            entry_ids_to_remove=set(data["_dataset"].keys()),
            precomputed_original_dataset_keys=precomputed_original_dataset_keys,
            save_path=path,
            rng=rng,
        )

        out._dataset = data["_dataset"]
        out._unlabelled_dataset = SlotSet(
            [
                entry_id
                for entry_id in original_dataset.keys()
                if entry_id not in out._dataset
            ]
        )
        out.messages = data["messages"]
        out._given_nexts = data["_given_nexts"]
        out._cached_subsample = data["_cached_subsample"]
        out._validate = data["_validate"]

        with open(path / "label_value_encoder.pickle", "rb") as file:
            out._label_value_encoder = pickle.load(file)
        with open(path / "bandit_explorer.pickle", "rb") as file:
            out._bandit_explorer = pickle.load(file)
        # out._model = DummyClassificationModel(n_classes=len(data["label_values"]))
        with open(path / "model.pickle", "rb") as file:
            out._model = pickle.load(file)

        return out
