import json
import pickle
import warnings
from collections.abc import Callable
from pathlib import Path
from statistics import multimode
from threading import Lock
from typing import Any

import numpy as np
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

Labelling = str
EntryId = int | str


class ActiveLearningBackend:
    n_kickstart: int
    labels: list[str]

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
    # ([entry, labelling, user_id, timestamp], is_validation, true_labelling)
    _dataset: dict[EntryId, tuple[list[tuple[str, int, int, float]], bool, int]]
    _cached_subsample: list[EntryId]
    _given_nexts: list[EntryId]

    _label_encoder: LabelEncoder
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
        labels: list[str],
        *,
        # model_factory: Callable[[], ClassificationModel],
        policy: Policy | None = None,
        initial_labelled_dataset: dict[EntryId, Labelling] | None = None,
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

        self.labels = labels
        self._label_encoder = LabelEncoder()
        self._label_encoder.fit(labels)

        if precomputed_original_dataset_keys is None:
            self._unlabelled_dataset = SlotSet(original_dataset.keys())
        else:
            self._unlabelled_dataset = precomputed_original_dataset_keys.shallow_copy()
        if entry_ids_to_remove is not None:
            for entry_id in entry_ids_to_remove:
                self._unlabelled_dataset.remove(entry_id)
        if initial_labelled_dataset is not None:
            for entry_id, label in initial_labelled_dataset.items():
                # TODO: Keep track of it
                self._dataset[entry_id] = (
                    [(original_dataset[entry_id], self._encode(label), -1, -1)],
                    False,
                    self._encode(label),
                )
                self._unlabelled_dataset.remove(entry_id)

        self._rng = rng

        # Start cache ranromly while we dont have a trained model
        cached_subsample_is = self._rng.choice(
            np.arange(len(self._unlabelled_dataset)),
            min(self.subsample_size[-2], len(self._unlabelled_dataset)),
            replace=False,
        )
        self._cached_subsample = [self._unlabelled_dataset[i] for i in cached_subsample_is]
        self._given_nexts = []
        self._validate = False

        # self._bandit_explorer = EpsilonGreedy(n_levers=2, epsilon=0.1, rng=self._rng)
        # self._bandit_explorer = ConformalUCB(
        #     n_levers=2, reward_upper_bound=1, rng=self._rng
        # )
        self._bandit_explorer = DummyBandit(
            n_levers=len(labels), prob_levers=[0.8, 0.2], rng=self._rng
        )
        self._policy = policy

        self._data_lock = Lock()
        self._cache_lock = Lock()
        self._model = DummyClassificationModel(n_classes=len(self.labels))

        # If we have enought entries we start training
        self._training = False
        self._retrain = False
        self._count_since_last_train = 0

    def _encode(self, labelling: Labelling | list[Labelling]) -> int | list[int]:
        if isinstance(labelling, list | np.ndarray):
            return self._label_encoder.transform(labelling).tolist()
        else:
            return self._label_encoder.transform([labelling])[0]

    def _decode(self, encoded_label: int | list[int] | np.ndarray) -> str | list[str]:
        if isinstance(encoded_label, list | np.ndarray):
            return self._label_encoder.inverse_transform(encoded_label).tolist()
        else:
            return self._label_encoder.inverse_transform([encoded_label])[0]

    def _compute_metric_with_bootstrap(
        self,
        metric_func: Callable[..., float | list[float] | dict[str, float]],
        alpha: float = 0.05,
        n_bootstrap: int = 1000,
        **metric_kwargs: Any,  # noqa: ANN401 # Necessary for sklearn metric flexibility
    ) -> tuple[float, float] | list[tuple[float, float]] | dict[str, tuple[float, float]]:
        """
        Wrapper method for computing metrics with bootstrapping.

        Args:
            metric_func: Metric function to evaluate (sklearn metric or custom function)
            alpha: Significance level for confidence intervals (default 0.05 for 95% CI)
            n_bootstrap: Number of bootstrap samples (default 1000)
            **metric_kwargs: Additional keyword arguments for the metric function

        Returns:
            - tuple[float, float]: (lower_bound, upper_bound) for single metric
            - list[tuple[float, float]]: bounds for each metric in list
            - dict[str, tuple[float, float]]: bounds for each named metric in dict
        """
        with self._data_lock:
            val_dataset = self._val_dataset
            model = self._model

        if len(val_dataset) == 0:
            return (0.0, 1.0)

        # Prepare data
        texts = [self._original_dataset[entry_id] for entry_id in val_dataset.keys()]
        y_true = np.array(list(val_dataset.values()))
        y_pred = np.array(model.raw_predictions(texts))

        # Check for single-class case early
        unique_classes = np.unique(y_true)
        if len(unique_classes) < 2:
            # For single-class validation data, return appropriate default values
            return (0.0, 1.0)

        # Handle probability predictions if needed
        y_pred_proba = None
        if "needs_proba" in metric_kwargs and metric_kwargs.pop("needs_proba"):
            y_pred_proba = np.array(model.predict_proba(texts))

        n_samples = len(y_true)
        rng = np.random.default_rng()

        # Collect bootstrap results for each metric
        bootstrap_results = []
        failed_samples = 0
        skipped_single_class = 0

        for _ in range(n_bootstrap):
            # Bootstrap resampling
            indices = rng.choice(n_samples, size=n_samples, replace=True)
            y_true_boot = y_true[indices]
            y_pred_boot = y_pred[indices]

            # Check if bootstrap sample has multiple classes
            unique_boot_classes = np.unique(y_true_boot)
            if len(unique_boot_classes) < 2:
                # Skip this bootstrap sample if it only has one class
                skipped_single_class += 1
                continue

            # Additional check for ROC AUC: need reasonable class balance
            if (
                "needs_proba" in metric_kwargs
                and hasattr(metric_func, "__name__")
                and "roc_auc" in metric_func.__name__
            ):
                # For ROC AUC, check if we have at least 2 samples of each class
                class_counts = np.bincount(y_true_boot.astype(int))
                if np.min(class_counts[class_counts > 0]) < 2:
                    skipped_single_class += 1
                    continue

            try:
                # Suppress sklearn warnings during bootstrap computation
                with warnings.catch_warnings():
                    warnings.filterwarnings("ignore", category=UserWarning, module="sklearn")
                    warnings.filterwarnings("ignore", message=".*Only one class is present.*")
                    warnings.filterwarnings("ignore", message=".*A single label was found.*")

                    if y_pred_proba is not None:
                        y_pred_proba_boot = y_pred_proba[indices]
                        score = metric_func(y_true_boot, y_pred_proba_boot, **metric_kwargs)
                    else:
                        score = metric_func(y_true_boot, y_pred_boot, **metric_kwargs)

                bootstrap_results.append(score)

            except (ValueError, ZeroDivisionError):
                failed_samples += 1
                # Handle edge cases - append appropriate zero values
                if hasattr(metric_func, "__name__"):
                    # Try to get a sample result to understand the structure
                    try:
                        sample_result = metric_func(
                            y_true[: min(2, len(y_true))],
                            y_pred[: min(2, len(y_true))],
                            **metric_kwargs,
                        )
                        if isinstance(sample_result, dict):
                            bootstrap_results.append(dict.fromkeys(sample_result.keys(), 0.0))
                        elif isinstance(sample_result, list | np.ndarray):
                            bootstrap_results.append([0.0] * len(sample_result))
                        else:
                            bootstrap_results.append(0.0)
                    except Exception:
                        bootstrap_results.append(0.0)
                else:
                    bootstrap_results.append(0.0)

        # Report bootstrap statistics if there were issues
        if skipped_single_class > 0 or failed_samples > 0:
            metric_name = getattr(metric_func, "__name__", "metric")
            print(
                f"Bootstrap {metric_name}: {len(bootstrap_results)} successful, "
                f"{skipped_single_class} skipped (single-class), {failed_samples} failed"
            )

        # Determine result structure from first successful result
        if not bootstrap_results:
            return (0.0, 1.0)

        first_result = bootstrap_results[0]

        if isinstance(first_result, dict):
            # Handle dict[str, float] -> dict[str, tuple[float, float]]
            result = {}
            for key in first_result.keys():
                values = [
                    result[key] if isinstance(result, dict) else 0.0 for result in bootstrap_results
                ]
                values = np.array(values)
                lower = np.percentile(values, 100 * alpha / 2)
                upper = np.percentile(values, 100 * (1 - alpha / 2))
                result[key] = (float(lower), float(upper))
            return result

        elif isinstance(first_result, list | np.ndarray):
            # Handle list[float] -> list[tuple[float, float]]
            n_metrics = len(first_result)
            result = []
            for i in range(n_metrics):
                values = [
                    result[i] if isinstance(result, list | np.ndarray) and len(result) > i else 0.0
                    for result in bootstrap_results
                ]
                values = np.array(values)
                lower = np.percentile(values, 100 * alpha / 2)
                upper = np.percentile(values, 100 * (1 - alpha / 2))
                result.append((float(lower), float(upper)))
            return result

        else:
            # Handle float -> tuple[float, float]
            values = np.array(
                [
                    float(result) if isinstance(result, int | float) else 0.0
                    for result in bootstrap_results
                ]
            )
            lower = np.percentile(values, 100 * alpha / 2)
            upper = np.percentile(values, 100 * (1 - alpha / 2))
            return (float(lower), float(upper))

    def _cache_whether_to_validate(self) -> None:
        self._validate = self._bandit_explorer.select_lever() == 1

    def _train(self) -> None:
        self.message("Starting training.")
        # Load data
        with self._data_lock:
            unlabelled_ids = np.array(self._unlabelled_dataset)
            unlabelled = [self._original_dataset[entry_id] for entry_id in unlabelled_ids]
            unlabelled_dict = {
                entry_id: self._original_dataset[entry_id] for entry_id in unlabelled_ids
            }
            labelled = [
                (self._original_dataset[entry_id], labelling)
                for entry_id, labelling in self._train_dataset.items()
            ]
            validation = [
                (self._original_dataset[entry_id], labelling)
                for entry_id, labelling in self._val_dataset.items()
            ]
            rng = np.random.default_rng(seed=self._rng.integers(np.iinfo(int).max))
            # del self._model
            # self._model = DummyClassificationModel(n_classes=len(self.labels))
            with self._cache_lock:
                self._count_since_last_train = 0

        # Train new model
        if CLASSIFICATION_MODEL == "TfidfXGBoostClassifier":
            class_model = TfidfXGBoostClassifier(n_classes=len(self.labels))
        elif CLASSIFICATION_MODEL == "DebertaV3Wrapper":
            class_model = DebertaV3Wrapper(
                n_classes=len(self.labels),
                model="deberta_v3_base_en",
                verbose=0,
            )
        else:
            # Fallback to dummy model if no specific model is configured
            class_model = DummyClassificationModel(n_classes=len(self.labels))

        model = ConformalPredictor(
            model=class_model,
            alpha=0.1,
            n_classes=len(self.labels),
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
                    [sorted_ids[i] for i in dist_argmin(kmean.cluster_centers_, to_cluster_emb)[0]]
                )
            )

            # TODO: recall_prob to solve untrusted labellings
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
                new_cache = new_cache[np.isin(new_cache, self._unlabelled_dataset.array)].tolist()

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
        self.metrics_strs.append(f"n labeled: {len(labelled) + len(validation)}")

        # Count class distribution in training set
        train_class_counts = {}
        for _, label in labelled:
            label_name = self._decode(label)
            train_class_counts[label_name] = train_class_counts.get(label_name, 0) + 1

        # Count class distribution in validation set
        val_class_counts = {}
        for _, label in validation:
            label_name = self._decode(label)
            val_class_counts[label_name] = val_class_counts.get(label_name, 0) + 1

        # Format train class distribution
        train_dist = ", ".join([f"{label}: {count}" for label, count in train_class_counts.items()])
        self.metrics_strs.append(f"Train ({len(labelled)}): {train_dist}")

        # Format validation class distribution
        val_dist = ", ".join([f"{label}: {count}" for label, count in val_class_counts.items()])
        self.metrics_strs.append(f"Val ({len(validation)}): {val_dist}")
        lower, upper = self.peek_auc_roc_ovr(alpha=0.05)
        self.metrics_strs.append(
            rf"AUC_ROC: \({(lower + upper) / 2:.2f} \pm {(upper - lower) / 2:.2f}\)"
        )
        lower, upper = self.peek_accuracy(alpha=0.05)
        self.metrics_strs.append(
            rf"Accuracy: \({(lower + upper) / 2:.2f} \pm {(upper - lower) / 2:.2f}\)"
        )
        if len(self.labels) == 2:
            lower, upper = self.peek_precision(target=self.labels[1], alpha=0.05)
            self.metrics_strs.append(
                rf"Precision: \({(lower + upper) / 2:.2f} \pm {(upper - lower) / 2:.2f}\)"
            )
            lower, upper = self.peek_recall(target=self.labels[1], alpha=0.05)
            self.metrics_strs.append(
                rf"Recall: \({(lower + upper) / 2:.2f} \pm {(upper - lower) / 2:.2f}\)"
            )
            lower, upper = self.peek_specificity(target=self.labels[1], alpha=0.05)
            self.metrics_strs.append(
                rf"Specificity: \({(lower + upper) / 2:.2f} \pm {(upper - lower) / 2:.2f}\)"
            )
        else:
            for label_name in self.labels:
                lower, upper = self.peek_precision(target=label_name, alpha=0.05)
                self.metrics_strs.append(
                    rf"Precision ({label_name}): "
                    rf"\({(lower + upper) / 2:.2f} \pm {(upper - lower) / 2:.2f}\)"
                )
                lower, upper = self.peek_recall(target=label_name, alpha=0.05)
                self.metrics_strs.append(
                    rf"Recall ({label_name}): "
                    rf"\({(lower + upper) / 2:.2f} \pm {(upper - lower) / 2:.2f}\)"
                )
                lower, upper = self.peek_specificity(target=label_name, alpha=0.05)
                self.metrics_strs.append(
                    rf"Specificity ({label_name}): "
                    rf"\({(lower + upper) / 2:.2f} \pm {(upper - lower) / 2:.2f}\)"
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
            label_id: entry[2]
            for label_id, entry in self._dataset.items()
            if not entry[1] and entry[2] != -1
        }

    @property
    def _val_dataset(self) -> dict[EntryId, int]:
        return {
            label_id: entry[2]
            for label_id, entry in self._dataset.items()
            if entry[1] and entry[2] != -1
        }

    def message(self, msg) -> None:
        print(msg)
        with self.msg_lock:
            self.messages.append(msg)

    def update_trustness(self, entry_id: EntryId) -> None:
        # Updates trustness following data structures.
        labellings = [labelling for labelling, *_ in enumerate(self._dataset[entry_id][0])]
        modes = multimode(labellings)
        if len(modes) == 1:
            # We have a single mode, we can trust this entry
            self._dataset[entry_id][2] = modes[0]
        else:
            # We have multiple modes, we cannot trust this entry
            self._dataset[entry_id][2] = -1

    # TODO: Verify if adding timestamp and user breaks this.int,
    def sync_labelling(self, labelled_data: dict[EntryId, Labelling]) -> None:
        with self._data_lock:
            for entry_id, labelling in labelled_data.items():
                # We add everything new to self._train_dataset because manually
                # labelled data can be biased.
                # Verify if entry in
                # false is_validate
                if entry_id not in self._dataset:
                    self._dataset[entry_id] = (
                        [
                            (
                                self._original_dataset[entry_id],
                                self._encode(labelling),
                                -1,  # user_id
                                -1,
                            ),  # timestamp
                        ],
                        False,
                        self._encode(labelling),
                    )
                    self._unlabelled_dataset.remove(entry_id)
                    self._count_since_last_train += 1

        # FIXME, Recalculate bandit rewards?!?!?!?!

    def submit_labelling(
        self,
        entry_id: EntryId,
        labelling: Labelling,
        user_id: int,
        timestamp: float,
        check_given: bool = True,
    ) -> None:
        if not isinstance(labelling, Labelling):
            raise TypeError("`labelling` must be a `Labelling`")

        if check_given:
            assert entry_id in self._given_nexts, "submitted an unexpected label"
        # inf_auc_before, _ = self.peek_auc_roc_ovr(alpha=0.1)

        with self._data_lock:
            # Overwrite _validate if we are not using bandit
            if not USE_BANDIT:
                rand = self._rng.uniform()
                current_label = self._encode(labelling)

                # Calculate class distribution in current validation dataset
                val_labels = list(self._val_dataset.values())
                if len(val_labels) > 0:
                    # Count occurrences of current label in validation set
                    current_label_count = sum(1 for label in val_labels if label == current_label)

                    if current_label_count == 0:
                        # Current label has no representation in validation set
                        # Use maximum probability to encourage adding it
                        prob = min(1.0, len(self.labels) * VALIDATE_PROB)
                    else:
                        # Current label proportion in validation set
                        current_label_proportion = current_label_count / len(val_labels)

                        # Dynamic prob: (n_classes/(n_classes-1)) * (1 - proportion) * VALIDATE_PROB
                        # This gives low prob for overrepresented, high prob for underrepresented
                        prob = (
                            (len(self.labels) / (len(self.labels) - 1))
                            * (1 - current_label_proportion)
                            * VALIDATE_PROB
                        )
                else:
                    # No validation data yet, use base probability
                    prob = VALIDATE_PROB

                print(labelling, prob)

                self._validate = rand < prob

            # TODO: Test this.
            if entry_id not in self._dataset:
                self._dataset[entry_id] = (
                    [
                        (
                            self._original_dataset[entry_id],
                            self._encode(labelling),
                            user_id,
                            timestamp,
                        ),
                    ],
                    self._validate,
                    self._encode(labelling),
                )
            else:
                self._dataset[entry_id][0].append(
                    (
                        self._original_dataset[entry_id],
                        self._encode(labelling),
                        user_id,
                        timestamp,
                    )
                )
                self.update_trustness(entry_id)

            if entry_id in self._unlabelled_dataset:
                self.message(f"removing from unlabeled: {entry_id}")
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
        #     )  # dict lookup so that we get an error if an unexpected value shows up
        #       # (e.g. because we've changed the number of levers)
        #     self._policy.inform(reward)

        # Update cached_subsample and validate
        with self._cache_lock:
            assert len(self._cached_subsample) >= 1  # FIXME: Better treatment for this
            self._cached_subsample = self._cached_subsample[1:]
            self._count_since_last_train += 1
        self._cache_whether_to_validate()

    def peek_predictions(self, *, alpha: float) -> float:
        with self._data_lock:
            model = self._model
            unlabeled_data = self._unlabelled_dataset
        if len(self.subsample_size) == 3:
            ids = self._rng.integers(len(unlabeled_data), size=(self.subsample_size[-3]))
            unlabeled_data = [self._original_dataset[unlabeled_data[i]] for i in ids]
        preds = model.predict(unlabeled_data)
        return np.mean([len(pred) in [0, 1] for pred in preds])

    def peek_accuracy(self, *, alpha: float) -> tuple[float, float]:
        return self._compute_metric_with_bootstrap(accuracy_score, alpha=alpha)

    def peek_precision(self, *, target: Labelling, alpha: float) -> tuple[float, float]:
        target_enc = self._encode(target)
        # Include all possible labels for sklearn metrics
        all_labels = list(range(len(self.labels)))
        return self._compute_metric_with_bootstrap(
            precision_score,
            alpha=alpha,
            pos_label=target_enc,
            average="binary" if len(self.labels) == 2 else "macro",
            zero_division=0,
            labels=all_labels,
        )

    def peek_recall(self, *, target: Labelling, alpha: float) -> tuple[float, float]:
        target_enc = self._encode(target)
        return self._compute_metric_with_bootstrap(
            recall_score,
            alpha=alpha,
            pos_label=target_enc,
            average="binary" if len(self.labels) == 2 else "macro",
            zero_division=0,
        )

    def _specificity_score(self, y_true, y_pred, *, pos_label=1, **_kwargs) -> float:
        """Calculate specificity (true negative rate) for a specific target class."""
        # Check for single-class case
        unique_true = np.unique(y_true)

        if len(unique_true) < 2:
            # Single class in true labels - return 0.0 for specificity
            return 0.0

        # Include all possible labels for confusion matrix
        all_labels = list(range(len(self.labels)))
        cm = confusion_matrix(y_true, y_pred, labels=all_labels)

        if len(self.labels) == 2:
            # Binary classification
            if cm.shape == (2, 2):
                tn, fp, _, _ = cm.ravel()
                return tn / (tn + fp) if (tn + fp) > 0 else 0.0
            else:
                return 0.0
        else:
            # Multiclass classification - calculate specificity for the target class
            # Convert to binary: target class vs all others
            y_true_binary = (y_true == pos_label).astype(int)
            y_pred_binary = (y_pred == pos_label).astype(int)

            cm_binary = confusion_matrix(y_true_binary, y_pred_binary, labels=[0, 1])
            if cm_binary.shape == (2, 2):
                tn, fp, _, _ = cm_binary.ravel()
                return tn / (tn + fp) if (tn + fp) > 0 else 0.0
            else:
                # Edge case: only one class present
                return 0.0

    def peek_specificity(self, *, target: Labelling, alpha: float) -> tuple[float, float]:
        target_enc = self._encode(target)
        return self._compute_metric_with_bootstrap(
            self._specificity_score, alpha=alpha, pos_label=target_enc
        )

    def peek_auc_roc_ovr(self, *, alpha: float) -> tuple[float, float]:
        with self._data_lock:
            val_dataset = self._val_dataset

        if len(val_dataset) == 0:
            return (0.0, 1.0)

        # Check if we have multiple classes in validation data
        unique_classes = np.unique(list(val_dataset.values()))
        if len(unique_classes) < 2:
            return (0.0, 1.0)

        if len(self.labels) == 2:
            # For binary classification, use standard binary AUC
            return self._compute_metric_with_bootstrap(roc_auc_score, alpha=alpha, needs_proba=True)
        else:
            # For multiclass, use one-vs-rest averaging
            return self._compute_metric_with_bootstrap(
                roc_auc_score, alpha=alpha, needs_proba=True, multi_class="ovr", average="macro"
            )

    def export_preditictions(
        self,
        entry_ids: list[EntryId] | None = None,
        alpha: float = 0.95,
    ) -> dict[EntryId, list[Labelling]]:
        if isinstance(self._model, DummyClassificationModel):
            raise ValueError(
                "Trained model not available, please add more labels to trigger a model training."
            )
        with self._data_lock:
            unlabelled_ids = entry_ids or np.array(self._unlabelled_dataset)
            unlabelled = [self._original_dataset[entry_id] for entry_id in unlabelled_ids]
            train_dataset = self._train_dataset
            labelled = [
                (entry, labelling)
                for entry, labelling in train_dataset.values()  # type: ignore
            ]
            labelled_data = [(entry_id, entry[-1]) for entry_id, entry in self._dataset.items()]
            validation_dataset = self._val_dataset
            validation = [(entry, labelling) for entry, labelling in validation_dataset.values()]
        self._model.train(labelled, validation, skip_model_train=True, alpha=alpha)

        decode = {self._encode(label): label for label in self.labels}

        data = {
            entry_id: [decode[p] for p in pred]
            for entry_id, pred in zip(unlabelled_ids, self._model.predict(unlabelled), strict=False)
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
                            "labels": self.labels,
                            "_cached_subsample": self._cached_subsample,
                            "_validate": bool(self._validate),
                            "_given_nexts": self._given_nexts,
                        }
                    ),
                    file,
                )

            with open(path / "bandit_explorer.pickle", "wb") as file:
                pickle.dump(self._bandit_explorer, file)
            with open(path / "label_encoder.pickle", "wb") as file:
                pickle.dump(self._label_encoder, file)
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

        out = cls(
            original_dataset,
            labels=data["labels"],
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
            [entry_id for entry_id in original_dataset.keys() if entry_id not in out._dataset]
        )
        out.messages = data["messages"]
        out._given_nexts = data["_given_nexts"]
        out._cached_subsample = data["_cached_subsample"]
        out._validate = data["_validate"]

        with open(path / "label_encoder.pickle", "rb") as file:
            out._label_encoder = pickle.load(file)
        with open(path / "bandit_explorer.pickle", "rb") as file:
            out._bandit_explorer = pickle.load(file)
        # out._model = DummyClassificationModel(n_classes=len(data["labels"]))
        with open(path / "model.pickle", "rb") as file:
            out._model = pickle.load(file)

        return out
