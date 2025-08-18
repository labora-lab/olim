import keras_hub

from . import ClassificationModel


class DebertaV3Wrapper(ClassificationModel):
    def __init__(
        self,
        n_classes: int | None = None,
        model: str = "deberta_v3_base_en",
        verbose: int = 0,
    ) -> None:
        # Load the pretrained DeBERTa V3 model
        self.verbose = verbose
        if model.startswith("deberta"):
            backbone = keras_hub.models.DebertaV3Classifier
        elif model.startswith("bert"):
            backbone = keras_hub.models.BertClassifier
        elif model.startswith("albert"):
            backbone = keras_hub.models.AlbertClassifier
        else:
            raise NotImplementedError(f"Model {model} not implemented.")
        self.model = backbone.from_preset(model, num_classes=n_classes)

    def train(
        self,
        labelled_data: list[tuple[str, int]],
        epochs: int = 5,
        batch_size: int = 6,
        verbose: int = 0,
    ) -> None:
        """
        Trains the DeBERTa V3 model on the provided labeled data.
        """
        texts, labels = zip(*labelled_data, strict=False)  # Separate texts and labels
        self.model.compile(
            optimizer="adam",
            loss="sparse_categorical_crossentropy",
            metrics=["accuracy"],
        )
        self.model.fit(
            list(texts),
            list(labels),
            epochs=epochs,
            batch_size=batch_size,
            verbose=self.verbose,
        )

    def predict(self, unlabelled_data: list[str]) -> list[int]:
        """
        Predicts the most likely labels for the given unlabeled data.
        """
        if len(unlabelled_data) == 0:
            return []
        predictions = self.model.predict(unlabelled_data, verbose=self.verbose)
        return predictions.argmax(axis=1).tolist()  # Convert logits to label indices

    def get_embeddings(self, data: list[str]) -> list[list[float]]:
        """
        Generates embeddings for the given input data.
        """
        if len(data) == 0:
            return []
        # Get token ids, restrict to 100
        token_ids = self.model.preprocess_samples(data)["token_ids"][:, :100]
        # Get embeddings mapping
        embeddings = self.model.backbone.token_embedding.get_weights()[0]
        # Embed tokens
        embedded_data = embeddings[token_ids]
        # Flatten vectors on entries
        embedded_data = embedded_data.reshape((token_ids.shape[0], -1))
        return embedded_data

    def predict_proba(self, unlabelled_data: list[str]) -> list[list[float]]:
        """
        Predicts the probabilities of each label for the given unlabeled data.
        """
        if len(unlabelled_data) == 0:
            return []
        return self.model.predict(unlabelled_data, verbose=self.verbose)
