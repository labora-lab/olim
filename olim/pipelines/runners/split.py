from sklearn.model_selection import train_test_split

from olim.pipelines.runners.base import BlockContext, BlockRunner, RunResult

_RANDOM_STATE = 42


class TrainTestSplitRunner(BlockRunner):
    """Splits the row indices into train/test, stratified by label. Stores only
    indices into the feature matrix/labels — slicing a CSR matrix is cheap."""

    def run(self, ctx: BlockContext) -> RunResult:
        acc = self.load(ctx)
        labels = acc["labels"]
        test_size = ctx.config.get("test_size", 0.25)
        train_idx, test_idx = train_test_split(
            list(range(len(labels))),
            test_size=test_size,
            random_state=_RANDOM_STATE,
            stratify=labels,
        )
        acc["train_idx"] = train_idx
        acc["test_idx"] = test_idx
        return RunResult(
            artifact_ref=self.save(ctx, acc),
            metrics={"n_train": len(train_idx), "n_test": len(test_idx)},
        )
