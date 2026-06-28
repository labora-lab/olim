from sklearn.feature_extraction.text import TfidfVectorizer

from olim.pipelines.runners.base import BlockContext, BlockRunner, RunResult


class TfidfRunner(BlockRunner):
    """Seeds the accumulator: vectorizes the item texts into a feature matrix
    and carries the row spine (item_ids + labels) downstream blocks align to."""

    def run(self, ctx: BlockContext) -> RunResult:
        if ctx.data is None:
            raise ValueError("tfidf needs training data")
        acc = self.load(ctx)
        vectorizer = TfidfVectorizer(ngram_range=(1, 1))
        features = vectorizer.fit_transform(ctx.data.texts)
        acc["item_ids"] = ctx.data.item_ids
        acc["labels"] = ctx.data.labels
        acc["features"] = features
        acc["vectorizer"] = vectorizer
        return RunResult(
            artifact_ref=self.save(ctx, acc),
            metrics={"n_features": features.shape[1], "n_samples": features.shape[0]},
        )
