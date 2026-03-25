from collections.abc import Callable

import numpy as np
import numpy.typing as npt
from sklearn.metrics import accuracy_score, precision_score, recall_score, roc_auc_score

# Type aliases
IntArray = npt.NDArray[np.int64]
FloatArray = npt.NDArray[np.float64]


def accuracy(
    label_values: IntArray, preds: IntArray, label_proba: FloatArray | None = None
) -> float:
    return float(accuracy_score(label_values, preds))


def precision(
    label_values: IntArray,
    preds: IntArray,
    label_proba: FloatArray | None = None,
    target: int | None = None,
) -> float:
    if target is None:
        raise ValueError("target parameter is required for precision metric")
    binary_labels = (label_values == target).astype(int)
    binary_preds = (preds == target).astype(int)
    return float(precision_score(binary_labels, binary_preds, zero_division=0))


def recall(
    label_values: IntArray,
    preds: IntArray,
    label_proba: FloatArray | None = None,
    target: int | None = None,
) -> float:
    if target is None:
        raise ValueError("target parameter is required for recall metric")
    binary_labels = (label_values == target).astype(int)
    binary_preds = (preds == target).astype(int)
    return float(recall_score(binary_labels, binary_preds, zero_division=0))


def specificity(
    label_values: IntArray,
    preds: IntArray,
    label_proba: FloatArray | None = None,
    target: int | None = None,
) -> float:
    """Compute specificity (true negative rate) for target class"""
    if target is None:
        raise ValueError("target parameter is required for specificity metric")

    # Specificity is recall for the negative class
    binary_labels = (label_values != target).astype(int)
    binary_preds = (preds != target).astype(int)
    return float(recall_score(binary_labels, binary_preds, zero_division=0))


def auc_roc(
    label_values: IntArray,
    preds: IntArray,
    label_proba: FloatArray | None = None,
    target: int | None = None,
    **kwargs,
) -> float:
    if label_proba is None:
        raise ValueError("label_proba parameter is required for auc_roc metric")

    # If target is None, compute macro-averaged AUC (one-vs-rest)
    if target is None:
        unique_label_values = np.unique(label_values)

        if len(unique_label_values) < 2:
            return 0

        # For binary classification, use standard AUC
        if len(unique_label_values) == 2:
            return float(roc_auc_score(label_values, label_proba[:, 1]))

        # For multiclass, use OvR
        try:
            return float(
                roc_auc_score(label_values, label_proba, multi_class="ovr", average="macro")
            )
        except ValueError:
            return 0

    # Single target AUC
    binary_labels = (label_values == target).astype(int)
    target_probs = label_proba[:, target]

    if len(np.unique(binary_labels)) < 2:
        return 0

    return float(roc_auc_score(binary_labels, target_probs))


def bootstrap_metric(
    metric_fn: Callable,
    label_values: IntArray,
    preds: IntArray,
    label_proba: FloatArray | None = None,
    n_iter: int = 1000,
    ci_alpha: float = 0.05,
    **kwargs,
) -> tuple[float, float, float]:
    """Wrap any metric function with percentile bootstrap confidence intervals.

    Args:
        metric_fn: A metric function with signature (label_values, preds, label_proba, **kwargs)
        label_values: True labels
        preds: Predicted labels
        label_proba: Predicted probabilities (optional)
        n_iter: Number of bootstrap iterations
        ci_alpha: Significance level (0.05 = 95% CI)
        **kwargs: Extra kwargs forwarded to metric_fn

    Returns:
        (point_estimate, ci_low, ci_high)
    """
    rng = np.random.default_rng(42)
    n = len(label_values)
    boot_scores: list[float] = []
    for _ in range(n_iter):
        idx = rng.integers(0, n, size=n)
        lp = label_proba[idx] if label_proba is not None else None
        try:
            score = metric_fn(label_values[idx], preds[idx], label_proba=lp, **kwargs)
            boot_scores.append(score)
        except Exception:
            pass
    point = metric_fn(label_values, preds, label_proba=label_proba, **kwargs)
    if not boot_scores:
        return point, point, point
    return (
        point,
        float(np.percentile(boot_scores, 100 * ci_alpha / 2)),
        float(np.percentile(boot_scores, 100 * (1 - ci_alpha / 2))),
    )
