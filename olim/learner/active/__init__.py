from collections.abc import Callable
from copy import deepcopy

import numpy as np
from tqdm import tqdm

from ..eval.metrics import Metrics, evaluate_metrics
from ..models import ClassificationModel
from .policies import Policy


def simulate_single_sample_active_learn(
    model_factory: Callable[[], ClassificationModel],
    policy: Policy,
    train_labelled_dataset: list[tuple[str, int]],
    validation_labelled_dataset: list[tuple[str, int]],
    *,
    metrics: Metrics,
    n_kickstart: int,
    n_rounds: int,
    rng: np.random.Generator,
):
    train_labelled_dataset = deepcopy(
        train_labelled_dataset
    )  # We copy this because we mutate this list over time.
    dataset = []

    def add_sample(index: int) -> None:
        nonlocal dataset

        dataset.append(train_labelled_dataset[index])
        del train_labelled_dataset[index]

    # Kickstart:
    for _ in range(n_kickstart):
        add_sample(rng.integers(0, len(train_labelled_dataset)))
    model = model_factory()
    model.train(dataset)

    # Active learning loop:
    performance_over_time = [evaluate_metrics(metrics, model, validation_labelled_dataset)]
    for i in tqdm(range(n_rounds), desc="active learning"):
        add_sample(policy.query([text for text, label in train_labelled_dataset], model))

        del model  # just to be sure :)
        model = model_factory()
        model.train(dataset)

        performance_over_time.append(evaluate_metrics(metrics, model, validation_labelled_dataset))

    return performance_over_time
