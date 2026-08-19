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


def f1(
    label_values: IntArray,
    preds: IntArray,
    label_proba: FloatArray | None = None,
    target: int | None = None,
) -> float:
    """Harmonic mean of precision and recall for the target class."""
    if target is None:
        raise ValueError("target parameter is required for f1 metric")
    prec = precision(label_values, preds, target=target)
    rec = recall(label_values, preds, target=target)
    if prec + rec == 0:
        return 0.0
    return 2 * prec * rec / (prec + rec)


def macro(
    metric_fn: Callable,
    label_values: IntArray,
    preds: IntArray,
    label_proba: FloatArray | None = None,
    n_classes: int | None = None,
    **kwargs,
) -> float:
    """Unweighted mean of a per-class metric over every class.

    Averaging over classes rather than over samples keeps a majority class from
    hiding a model that never predicts the minority one — the reason a 90/10
    dataset can show 0.90 accuracy with a useless classifier.
    """
    if n_classes is None:
        targets = np.unique(np.concatenate((np.asarray(label_values), np.asarray(preds))))
    else:
        targets = np.arange(n_classes)
    if len(targets) == 0:
        return float("nan")
    scores = [
        metric_fn(label_values, preds, label_proba=label_proba, target=int(t), **kwargs)
        for t in targets
    ]
    return float(np.mean(scores))


def balanced_accuracy(
    label_values: IntArray,
    preds: IntArray,
    label_proba: FloatArray | None = None,
    n_classes: int | None = None,
    **kwargs,
) -> float:
    """Macro-averaged recall — chance level is 1/n_classes whatever the imbalance."""
    return macro(recall, label_values, preds, label_proba=label_proba, n_classes=n_classes)


def macro_f1(
    label_values: IntArray,
    preds: IntArray,
    label_proba: FloatArray | None = None,
    n_classes: int | None = None,
    **kwargs,
) -> float:
    return macro(f1, label_values, preds, label_proba=label_proba, n_classes=n_classes)


def macro_precision(
    label_values: IntArray,
    preds: IntArray,
    label_proba: FloatArray | None = None,
    n_classes: int | None = None,
    **kwargs,
) -> float:
    return macro(precision, label_values, preds, label_proba=label_proba, n_classes=n_classes)


def macro_recall(
    label_values: IntArray,
    preds: IntArray,
    label_proba: FloatArray | None = None,
    n_classes: int | None = None,
    **kwargs,
) -> float:
    return macro(recall, label_values, preds, label_proba=label_proba, n_classes=n_classes)


def auc_roc(
    label_values: IntArray,
    preds: IntArray,
    label_proba: FloatArray | None = None,
    target: int | None = None,
    **kwargs,
) -> float:
    """ROC AUC, or NaN when the input cannot support one.

    NaN rather than 0 on purpose: a hard 0 silently satisfies any "metric <=
    threshold" early-stop goal, which used to end the loop on round one.
    """
    if label_proba is None:
        raise ValueError("label_proba parameter is required for auc_roc metric")

    label_proba = np.asarray(label_proba)

    # If target is None, compute macro-averaged AUC (one-vs-rest)
    if target is None:
        unique_label_values = np.unique(label_values)

        if len(unique_label_values) < 2:
            return float("nan")

        # For binary classification, use standard AUC
        if len(unique_label_values) == 2 and label_proba.shape[1] == 2:
            return float(roc_auc_score(label_values, label_proba[:, 1]))

        # For multiclass, use OvR
        try:
            return float(
                roc_auc_score(label_values, label_proba, multi_class="ovr", average="macro")
            )
        except ValueError:
            return float("nan")

    # Single target AUC
    binary_labels = (label_values == target).astype(int)
    if target >= label_proba.shape[1]:
        return float("nan")
    target_probs = label_proba[:, target]

    if len(np.unique(binary_labels)) < 2:
        return float("nan")

    return float(roc_auc_score(binary_labels, target_probs))


def bootstrap_metric(
    metric_fn: Callable,
    label_values: IntArray,
    preds: IntArray,
    label_proba: FloatArray | None = None,
    n_iter: int = 1000,
    ci_alpha: float = 0.05,
    min_valid_frac: float = 0.5,
    **kwargs,
) -> tuple[float, float | None, float | None, float]:
    """Wrap any metric function with percentile bootstrap confidence intervals.

    Args:
        metric_fn: A metric function with signature (label_values, preds, label_proba, **kwargs)
        label_values: True labels
        preds: Predicted labels
        label_proba: Predicted probabilities (optional)
        n_iter: Number of bootstrap iterations
        ci_alpha: Significance level (0.05 = 95% CI)
        min_valid_frac: Minimum fraction of usable resamples for the CI to be reported
        **kwargs: Extra kwargs forwarded to metric_fn

    Returns:
        (point_estimate, ci_low, ci_high, valid_frac)

        ci_low/ci_high are None when too few resamples produced a finite score —
        on a handful of validation rows most draws are degenerate, and reporting a
        CI built from the surviving minority would overstate its precision.
    """
    rng = np.random.default_rng(42)
    n = len(label_values)
    boot_scores: list[float] = []
    for _ in range(n_iter):
        idx = rng.integers(0, n, size=n)
        lp = label_proba[idx] if label_proba is not None else None
        try:
            score = metric_fn(label_values[idx], preds[idx], label_proba=lp, **kwargs)
        except Exception:
            continue
        if score is not None and np.isfinite(score):
            boot_scores.append(float(score))
    point = metric_fn(label_values, preds, label_proba=label_proba, **kwargs)
    valid_frac = len(boot_scores) / n_iter if n_iter else 0.0
    if not boot_scores or valid_frac < min_valid_frac:
        return point, None, None, valid_frac
    return (
        point,
        float(np.percentile(boot_scores, 100 * ci_alpha / 2)),
        float(np.percentile(boot_scores, 100 * (1 - ci_alpha / 2))),
        valid_frac,
    )


def confusion_counts(
    label_values: IntArray, preds: IntArray, n_classes: int
) -> tuple[FloatArray, FloatArray, FloatArray]:
    """Per-class (true positives, false positives, false negatives) in one pass.

    Every macro metric below is a ratio of these three, so counting once is far
    cheaper than calling a scikit-learn scorer per class per bootstrap resample.
    """
    labels = np.asarray(label_values).astype(np.int64)
    predicted = np.asarray(preds).astype(np.int64)
    both = np.bincount(labels * n_classes + predicted, minlength=n_classes * n_classes)
    matrix = both.reshape(n_classes, n_classes).astype(float)
    tp = np.diag(matrix).copy()
    return tp, matrix.sum(axis=0) - tp, matrix.sum(axis=1) - tp


def macro_bundle(label_values: IntArray, preds: IntArray, n_classes: int) -> dict[str, float]:
    """accuracy plus the macro-averaged metrics, all from one confusion matrix."""
    tp, fp, fn = confusion_counts(label_values, preds, n_classes)
    total = tp.sum() + fp.sum()
    with np.errstate(invalid="ignore", divide="ignore"):
        precision_c = np.where(tp + fp > 0, tp / np.maximum(tp + fp, 1), 0.0)
        recall_c = np.where(tp + fn > 0, tp / np.maximum(tp + fn, 1), 0.0)
        f1_c = np.where(
            precision_c + recall_c > 0,
            2 * precision_c * recall_c / np.maximum(precision_c + recall_c, 1e-12),
            0.0,
        )
    return {
        "accuracy": float(tp.sum() / total) if total else float("nan"),
        "macro_precision": float(precision_c.mean()),
        "macro_recall": float(recall_c.mean()),
        "balanced_accuracy": float(recall_c.mean()),
        "macro_f1": float(f1_c.mean()),
    }


def bootstrap_bundle(
    bundle_fn: Callable,
    label_values: IntArray,
    preds: IntArray,
    label_proba: FloatArray | None = None,
    n_iter: int = 1000,
    ci_alpha: float = 0.05,
    min_valid_frac: float = 0.5,
) -> dict[str, tuple[float, float | None, float | None, float]]:
    """Bootstrap a whole family of metrics over one shared set of resamples.

    Resampling once for all metrics rather than once per metric keeps the intervals
    mutually consistent and cuts the cost proportionally — this runs on every active
    learning retrain, with an annotator waiting on it.

    Returns {name: (point, ci_low, ci_high, valid_frac)}.
    """
    rng = np.random.default_rng(42)
    n = len(label_values)
    collected: dict[str, list[float]] = {}
    for _ in range(n_iter):
        idx = rng.integers(0, n, size=n)
        lp = label_proba[idx] if label_proba is not None else None
        try:
            scores = bundle_fn(label_values[idx], preds[idx], lp)
        except Exception:
            continue
        for name, value in scores.items():
            if value is not None and np.isfinite(value):
                collected.setdefault(name, []).append(float(value))

    point = bundle_fn(label_values, preds, label_proba)
    out: dict[str, tuple[float, float | None, float | None, float]] = {}
    for name, value in point.items():
        draws = collected.get(name, [])
        valid = len(draws) / n_iter if n_iter else 0.0
        if not draws or valid < min_valid_frac:
            out[name] = (value, None, None, valid)
        else:
            out[name] = (
                value,
                float(np.percentile(draws, 100 * ci_alpha / 2)),
                float(np.percentile(draws, 100 * (1 - ci_alpha / 2))),
                valid,
            )
    return out
