from typing import Sequence
from pathlib import Path
import json
import pickle
from threading import Thread, Lock
from statistics import multimode

from icecream import ic
import numpy as np
from sklearn.preprocessing import LabelEncoder
from sklearn.cluster import KMeans
from sklearn.metrics import pairwise_distances_argmin_min as dist_argmin

from .active import ClassificationModel
from .models import DummyClassificationModel
from .models.conformal import ConformalPredictor
from .active.policies import Policy, ConformalUnsertantyPolicy
from .bandits import BanditExplorer, EpsilonGreedy, ConformalUCB, DummyBandit
from .utils import dict_to_list, SlotSet, sanitize_data
from .settings import CLASSIFICATION_MODEL, SKIP_AL, UNCERTAIN_PERC

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
    _train_dataset: dict[EntryId, tuple[str, int]]
    _val_dataset: dict[EntryId, tuple[str, int]]
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
        policy: Policy = ConformalUnsertantyPolicy(),
        initial_labelled_dataset: dict[EntryId, Labelling] | None = None,
        n_kickstart: int = 10,
        subsample_size: list[int] = [5_000, 1_000, 20],
        unbiased_evaluation: bool = False,
        entry_ids_to_remove: set[EntryId] | None = None,
        precomputed_original_dataset_keys: SlotSet[EntryId] | None = None,
        rng: np.random.Generator,
        save_path: Path | str | None = None,
    ):
        if not (isinstance(n_kickstart, int) and n_kickstart >= 1):
            raise TypeError("`n_kickstart` must be an `int` >= 1")

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
        self._cached_subsample = [
            self._unlabelled_dataset[i] for i in cached_subsample_is
        ]
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
        if isinstance(labelling, Labelling):
            return self._label_encoder.transform([labelling])[0]
        else:
            return self._label_encoder.transform(labelling)

    def _cache_whether_to_validate(self):
        self._validate = self._bandit_explorer.select_lever() == 1

    def _train(self):
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
                (entry, labelling) for entry, labelling in self._train_dataset.values()
            ]
            validation = [
                (entry, labelling) for entry, labelling in self._val_dataset.values()
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
        model = ConformalPredictor(
            model=class_model,
            alpha=0.1,
            n_classes=len(self.labels),
        )
        self.message("Instanced model")
        model.train(labelled, validation)  # , epochs=3)
        self.message("Done training")

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

            # TODO: recall_prob to solve untrusted labellings
            other_ids = sorted_ids[~np.isin(sorted_ids, best_ids)]
            rng.shuffle(best_ids)
            rng.shuffle(other_ids)

            new_cache = np.concatenate((best_ids, other_ids))
            if type(list(self._original_dataset)[0]) is int:
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
                if not SKIP_AL:
                    self._previous_cache_top = self._cached_subsample[0]
                    self._cached_subsample = new_cache
                self._model = model
                retrain = self._retrain
                self._retrain = False
                if not retrain:
                    self._training = False

        self.metrics_strs = ["Last trained model:"]
        self.metrics_strs.append(f"n labeled: {len(labelled) + len(validation)}")
        self.metrics_strs.append(f"split train/val: {len(labelled)}/{len(validation)}")
        l, h = self.peek_auc_roc_ovr(alpha=0.05)
        self.metrics_strs.append(
            rf"AUC_ROC: \({(l + h) / 2:.2f} \pm {(h - l) / 2:.2f}\)"
        )
        l, h = self.peek_accuracy(alpha=0.05)
        self.metrics_strs.append(
            rf"Accuracy: \({(l + h) / 2:.2f} \pm {(h - l) / 2:.2f}\)"
        )
        if len(self.labels) == 2:
            l, h = self.peek_precision(target=self.labels[1], alpha=0.05)
            self.metrics_strs.append(
                rf"Precision: \({(l + h) / 2:.2f} \pm {(h - l) / 2:.2f}\)"
            )
            l, h = self.peek_recall(target=self.labels[1], alpha=0.05)
            self.metrics_strs.append(
                rf"Recall: \({(l + h) / 2:.2f} \pm {(h - l) / 2:.2f}\)"
            )
        else:
            for lb in self.labels:
                l, h = self.peek_precision(target=lb, alpha=0.05)
                self.metrics_strs.append(
                    rf"Precision ({lb}): \({(l + h) / 2:.2f} \pm {(h - l) / 2:.2f}\)"
                )
                l, h = self.peek_recall(target=lb, alpha=0.05)
                self.metrics_strs.append(
                    rf"Recall ({lb}): \({(l + h) / 2:.2f} \pm {(h - l) / 2:.2f}\)"
                )
        self.metrics_strs.append(f"Conformal threshold: \({model.threshold}\)")
        conf_cov = self.peek_predictions(alpha=0.05) * 100
        self.metrics_strs.append(f"Conformal coverage: \({conf_cov:.1f} \%\)")

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

    def message(self, msg):
        print(msg)
        with self.msg_lock:
            self.messages.append(msg)

    def update_trustness(self, entry_id: EntryId) -> None:
        # Updates trustness following data structures.
        labellings = [
            labelling for labelling, *rest in enumerate(self._dataset[entry_id][0])
        ]
        modes = multimode(labellings)
        if len(modes) == 1:
            # We have a single mode, we can trust this entry
            self._dataset[entry_id][2] = modes[0]
        else:
            # We have multiple modes, we cannot trust this entry
            self._dataset[entry_id][2] = -1

    # TODO: Verify if adding timestamp and user breaks this.
    def sync_labelling(self, labelled_data: dict[EntryId, Labelling]) -> None:

        with self._data_lock:
            for entry_id, labelling in labelled_data.items():
                # We add everything new to self._train_dataset because manualy labelled data can be biased.
                # Verify if entry in
                # false is_validate
                if not (entry_id in self._dataset):
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
        inf_auc_before, _ = self.peek_auc_roc_ovr(alpha=0.1)

        with self._data_lock:
            # Overwrite _validade if we are not using bandit
            if not USE_BANDIT:
                rand = self._rng.uniform()
                is_other = [
                    d[1] != self._encode(labelling)
                    for _, d in self._val_dataset.items()
                ]
                prob = VALIDATE_PROB
                if len(is_other) > 10:
                    prob = prob * 2 * np.mean(is_other)
                self._validate = rand >= prob

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
        inf_auc_after, _ = self.peek_auc_roc_ovr(alpha=0.1)
        reward = inf_auc_after - inf_auc_before
        with self._data_lock:
            self._bandit_explorer.inform(
                {True: 1, False: 0}[self._validate], reward
            )  # dict lookup so that we get an error if an unexpected value shows up (e.g. because we've changed the number of levers)
            self._policy.inform(reward)

        # Update cached_subsample and validate
        with self._cache_lock:
            assert len(self._cached_subsample) >= 1  # FIXME: Beter treatment for this
            self._cached_subsample = self._cached_subsample[1:]
            self._count_since_last_train += 1
        self._cache_whether_to_validate()

    def peek_predictions(self, *, alpha: float):
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

    def peek_accuracy(self, *, alpha: float) -> tuple[float, float]:
        with self._data_lock:
            val_dataset = self._val_dataset
            model = self._model
        n = len(val_dataset)

        if n == 0:
            return (0.0, 1.0)

        # Batch process all samples using numpy operations
        texts, labels = zip(*val_dataset.values(), strict=False)
        proba_dicts = model.predict_proba(texts)  # Get all predictions at once

        # Convert probability dictionaries to numpy arrays
        classes = np.array(list(proba_dicts[0].keys()))
        prob_matrix = np.array([list(d.values()) for d in proba_dicts])
        predicted_indices = np.argmax(prob_matrix, axis=1)
        correct = (classes[predicted_indices] == np.array(labels)).astype(float)

        # Bootstrap resampling with numpy
        B = 1000
        bootstrap_means = np.zeros(B)
        rng = np.random.default_rng()

        for i in range(B):
            # Resample with replacement using numpy's choice
            resampled = rng.choice(correct, size=n, replace=True)
            bootstrap_means[i] = resampled.mean()

        # Calculate percentiles using numpy
        lower = np.percentile(bootstrap_means, 100 * alpha / 2)
        upper = np.percentile(bootstrap_means, 100 * (1 - alpha / 2))

        return (float(lower), float(upper))

    def peek_precision(self, *, target: Labelling, alpha: float) -> tuple[float, float]:
        with self._data_lock:
            val_dataset = self._val_dataset
            model = self._model

        target_enc = self._encode(target)
        texts, labels = (
            zip(*val_dataset.values(), strict=False) if val_dataset else ((), ())
        )
        n = len(texts)

        if n == 0:
            return (0.0, 1.0)

        # Batch predictions
        proba_dicts = model.predict_proba(texts)
        classes = np.array(list(proba_dicts[0].keys()))
        prob_matrix = np.array([list(d.values()) for d in proba_dicts])
        preds = classes[np.argmax(prob_matrix, axis=1)]
        labels = np.array(labels)

        # Target comparisons
        true_target = labels == target_enc
        pred_target = preds == target_enc

        # Bootstrap
        B = 1000
        boots = []
        rng = np.random.default_rng()

        for _ in range(B):
            idx = rng.choice(n, n, replace=True)
            tp = np.sum(true_target[idx] & pred_target[idx])
            fp = np.sum(pred_target[idx] & ~true_target[idx])
            boots.append(tp / (tp + fp) if (tp + fp) > 0 else 0.0)

        return tuple(
            np.percentile(boots, [100 * alpha / 2, 100 * (1 - alpha / 2)]).astype(float)
        )

    def peek_recall(self, *, target: Labelling, alpha: float) -> tuple[float, float]:
        with self._data_lock:
            val_dataset = self._val_dataset
            model = self._model

        target_enc = self._encode(target)
        texts, labels = (
            zip(*val_dataset.values(), strict=False) if val_dataset else ((), ())
        )
        n = len(texts)

        if n == 0:
            return (0.0, 1.0)

        # Batch predictions
        proba_dicts = model.predict_proba(texts)
        classes = np.array(list(proba_dicts[0].keys()))
        prob_matrix = np.array([list(d.values()) for d in proba_dicts])
        preds = classes[np.argmax(prob_matrix, axis=1)]
        labels = np.array(labels)

        # Target comparisons
        true_target = labels == target_enc
        pred_target = preds == target_enc

        # Bootstrap
        B = 1000
        boots = []
        rng = np.random.default_rng()

        for _ in range(B):
            idx = rng.choice(n, n, replace=True)
            tp = np.sum(true_target[idx] & pred_target[idx])
            fn = np.sum(true_target[idx] & ~pred_target[idx])
            boots.append(tp / (tp + fn) if (tp + fn) > 0 else 0.0)

        return tuple(
            np.percentile(boots, [100 * alpha / 2, 100 * (1 - alpha / 2)]).astype(float)
        )

    def peek_auc_roc_single(
        self, *, target: Labelling, alpha: float
    ) -> tuple[float, float]:
        with self._data_lock:
            val_dataset = self._val_dataset
            model = self._model

        target_enc = self._encode(target)
        texts, labels = (
            zip(*val_dataset.values(), strict=False) if val_dataset else ((), ())
        )

        if not texts:
            return (0.0, 1.0)

        # Get target probabilities
        proba_dicts = model.predict_proba(texts)
        target_probs = np.array([d[target_enc] for d in proba_dicts])
        labels = np.array(labels)

        # Split positive/negative
        pos_probs = target_probs[labels == target_enc]
        neg_probs = target_probs[labels != target_enc]
        n_pos, n_neg = len(pos_probs), len(neg_probs)

        if n_pos == 0 or n_neg == 0:
            return (0.0, 1.0)

        # Bootstrap with pairwise approximation
        B = 1000
        boots = []
        rng = np.random.default_rng()
        MAX_PAIRS = 900

        for _ in range(B):
            # Resample groups
            p = pos_probs[rng.choice(n_pos, n_pos, replace=True)]
            n = neg_probs[rng.choice(n_neg, n_neg, replace=True)]

            # Subsample if needed
            if len(p) * len(n) > MAX_PAIRS:
                p = rng.choice(p, min(30, len(p)), replace=False)
                n = rng.choice(n, min(30, len(n)), replace=False)

            # Vectorized comparison
            comp = p[:, None] > n[None, :]
            ties = p[:, None] == n[None, :]
            auc = (np.sum(comp) + 0.5 * np.sum(ties)) / (len(p) * len(n))
            boots.append(auc)

        return tuple(
            np.percentile(boots, [100 * alpha / 2, 100 * (1 - alpha / 2)]).astype(float)
        )

    def peek_auc_roc_ovr(self, *, alpha: float) -> tuple[float, float]:
        infs, sups = [], []
        for label in self.labels:
            l, u = self.peek_auc_roc_single(target=label, alpha=alpha)
            infs.append(l)
            sups.append(u)
        return (float(np.mean(infs)), float(np.mean(sups)))

    def make_predictions(
        self, texts: Sequence[str]
    ) -> list[tuple[str, tuple[dict[Labelling, float], Labelling]]]:
        with self._data_lock:
            texts = list(texts)
            probass = self._model.predict_proba(texts)
            point_preds = self._model.predict(texts)

        return [
            (
                text,
                (
                    {Labelling(y): float(p) for y, p in probas.items()},
                    Labelling(point_pred),
                ),
            )
            for text, probas, point_pred in zip(
                texts, probass, point_preds, strict=False
            )
        ]

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
            unlabelled = [
                self._original_dataset[entry_id] for entry_id in unlabelled_ids
            ]
            train_dataset = self._train_dataset
            labelled = [
                (entry, labelling) for entry, labelling in train_dataset.values()  # type: ignore
            ]
            labelled_data = [
                (entry_id, entry[-1]) for entry_id, entry in self._dataset.items()
            ]
            validation_dataset = self._val_dataset
            validation = [
                (entry, labelling) for entry, labelling in validation_dataset.values()
            ]
        self._model.train(labelled, validation, skip_model_train=True, alpha=alpha)

        decode = {self._encode(l): l for l in self.labels}

        data = {
            entry_id: [decode[p] for p in pred]
            for entry_id, pred in zip(
                unlabelled_ids, self._model.predict(unlabelled), strict=False
            )
        }
        for entry_id, labeling in labelled_data:
            data[entry_id] = [self._decode_single(labeling)]

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
    ):
        path = Path(path)

        with open(path / "fields.json") as file:
            data = json.load(file)
        with open(path / "policy.pickle", "rb") as file:
            policy = pickle.load(file)

        if type(list(original_dataset.keys())[0]) is int:
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

        with open(path / "label_encoder.pickle", "rb") as file:
            out._label_encoder = pickle.load(file)
        with open(path / "bandit_explorer.pickle", "rb") as file:
            out._bandit_explorer = pickle.load(file)
        # out._model = DummyClassificationModel(n_classes=len(data["labels"]))
        with open(path / "model.pickle", "rb") as file:
            out._model = pickle.load(file)

        return out
