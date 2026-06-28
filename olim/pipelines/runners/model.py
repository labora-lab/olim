from sklearn.linear_model import LogisticRegression

from olim.pipelines.runners.base import BlockContext, BlockRunner, RunResult


class LogRegRunner(BlockRunner):
    """Fits a logistic regression on the training rows. Thread parallelism is
    bounded by the worker's OMP/MKL env caps, not estimator args."""

    def run(self, ctx: BlockContext) -> RunResult:
        acc = self.load(ctx)
        features, labels, train_idx = acc["features"], acc["labels"], acc["train_idx"]
        y_train = [labels[i] for i in train_idx]
        model = LogisticRegression(max_iter=1000)
        model.fit(features[train_idx], y_train)
        acc["model"] = model
        return RunResult(
            artifact_ref=self.save(ctx, acc), metrics={"n_train": len(train_idx)}
        )
