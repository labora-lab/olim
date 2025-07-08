from typing import TYPE_CHECKING

import numpy as np
import numpy.typing as npt
from sklearn.metrics import accuracy_score, precision_score, recall_score, roc_auc_score

# Type aliases
IntArray = npt.NDArray[np.int64]
FloatArray = npt.NDArray[np.float64]

def accuracy(
    label_values: IntArray,
    preds: IntArray,
    label_proba: FloatArray | None = None
) -> float:
    return float(accuracy_score(label_values, preds))


def precision(
    label_values: IntArray,
    preds: IntArray,
    label_proba: FloatArray | None = None,
    target: int | None = None
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
    target: int | None = None
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
    target: int | None = None
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

        # For binary classification, use standard AUC
        if len(unique_label_values) == 2:
            return float(roc_auc_score(label_values, label_proba[:, 1]))

        # For multiclass, use OvR
        try:
            return float(roc_auc_score(label_values, label_proba, multi_class='ovr', average='macro'))
        except ValueError:
            return 0.5

    # Single target AUC
    binary_labels = (label_values == target).astype(int)
    target_probs = label_proba[:, target]

    if len(np.unique(binary_labels)) < 2:
        return 0.5

    return float(roc_auc_score(binary_labels, target_probs))
