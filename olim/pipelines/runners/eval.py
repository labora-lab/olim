from sklearn.metrics import accuracy_score, f1_score

from olim.pipelines.runners.base import BlockContext, BlockRunner, RunResult


class ClassificationMetricsRunner(BlockRunner):
    """Scores the fitted model on the held-out test rows. Produces only metrics
    (no heavy artifact), so its artifact_ref is None."""

    def run(self, ctx: BlockContext) -> RunResult:
        acc = self.load(ctx)
        features, labels, test_idx, model = (
            acc["features"],
            acc["labels"],
            acc["test_idx"],
            acc["model"],
        )
        y_true = [labels[i] for i in test_idx]
        y_pred = model.predict(features[test_idx])
        return RunResult(
            artifact_ref=None,
            metrics={
                "accuracy": float(accuracy_score(y_true, y_pred)),
                "f1_macro": float(f1_score(y_true, y_pred, average="macro")),
                "n_test": len(test_idx),
            },
        )
