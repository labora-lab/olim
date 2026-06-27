"""End-to-end HTTP tests for the pipeline factory: the create shell, the
"what fits next" candidates endpoint, append ordering, and the compatibility
gates (a model needs a split; conformal needs a calibration split).

The DB session is the rolled-back test session (see conftest)."""


def create_dataset(client, name="reviews"):
    r = client.post("/datasets", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def create_scheme(client, dataset_id):
    r = client.post(
        f"/schemes?dataset_id={dataset_id}",
        json={
            "name": "sentiment",
            "fields": [
                {
                    "type": "select",
                    "name": "s",
                    "options": [{"name": "p"}, {"name": "n"}],
                }
            ],
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def create_pipeline(client, name="clf"):
    dataset_id = create_dataset(client)
    scheme_id = create_scheme(client, dataset_id)
    r = client.post(
        f"/pipelines?dataset_id={dataset_id}&scheme_id={scheme_id}", json={"name": name}
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def candidate_types(client, pipeline_id):
    r = client.get(f"/pipelines/{pipeline_id}/candidates")
    assert r.status_code == 200, r.text
    return {c["type"] for c in r.json()}, r.json()


def append(client, pipeline_id, body):
    return client.post(f"/pipelines/{pipeline_id}/blocks", json=body)


class TestComposition:
    def test_empty_pipeline_offers_only_starters_with_config_schema(self, client):
        pid = create_pipeline(client)
        types, raw = candidate_types(client, pid)
        # starters consume the seed (raw_text / clean_text); no model, no split.
        assert {"lowercase", "tfidf", "count_vectorizer"} <= types
        assert "logreg" not in types
        assert "train_test_split" not in types
        # each candidate carries its config JSON Schema for the form.
        tfidf = next(c for c in raw if c["type"] == "tfidf")
        assert "max_features" in tfidf["config_schema"]["properties"]

    def test_split_then_model_unlock_in_order(self, client):
        pid = create_pipeline(client)
        assert (
            append(client, pid, {"type": "tfidf", "max_features": 5000}).status_code
            == 201
        )
        types, _ = candidate_types(client, pid)
        assert {"train_test_split", "train_calib_test_split"} <= types
        assert "logreg" not in types  # no split placed yet

        assert append(client, pid, {"type": "train_test_split"}).status_code == 201
        types, _ = candidate_types(client, pid)
        assert "logreg" in types

    def test_blocks_are_stored_in_append_order(self, client):
        pid = create_pipeline(client)
        append(client, pid, {"type": "lowercase"})
        append(client, pid, {"type": "tfidf"})
        r = client.get(f"/pipelines/{pid}")
        blocks = r.json()["blocks"]
        assert [b["type"] for b in blocks] == ["lowercase", "tfidf"]
        assert [b["position"] for b in blocks] == [0, 1]

    def test_config_is_persisted(self, client):
        pid = create_pipeline(client)
        append(client, pid, {"type": "tfidf", "max_features": 1234, "ngram_max": 2})
        block = client.get(f"/pipelines/{pid}").json()["blocks"][0]
        assert block["config"] == {"max_features": 1234, "ngram_max": 2}


class TestGates:
    def test_model_before_split_is_422(self, client):
        pid = create_pipeline(client)
        append(client, pid, {"type": "tfidf"})
        r = append(client, pid, {"type": "logreg"})
        assert r.status_code == 422
        assert "split" in str(r.json()["detail"])

    def test_conformal_needs_a_calibration_split(self, client):
        pid = create_pipeline(client)
        append(client, pid, {"type": "tfidf"})
        # a plain 2-way split does not produce `calibration`
        append(client, pid, {"type": "train_test_split"})
        append(client, pid, {"type": "logreg"})
        assert append(client, pid, {"type": "conformal"}).status_code == 422

    def test_conformal_ok_after_three_way_split(self, client):
        pid = create_pipeline(client)
        append(client, pid, {"type": "tfidf"})
        append(client, pid, {"type": "train_calib_test_split"})
        append(client, pid, {"type": "logreg"})
        assert (
            append(client, pid, {"type": "conformal", "alpha": 0.05}).status_code == 201
        )

    def test_bad_block_config_is_422_at_boundary(self, client):
        pid = create_pipeline(client)
        # alpha must be in (0,1); pydantic rejects before the service runs.
        r = append(client, pid, {"type": "conformal", "alpha": 5})
        assert r.status_code == 422


class TestErrors:
    def test_missing_pipeline_is_404(self, client):
        r = client.get("/pipelines/999")
        assert r.status_code == 404

    def test_create_with_missing_scheme_is_404(self, client):
        dataset_id = create_dataset(client)
        r = client.post(
            f"/pipelines?dataset_id={dataset_id}&scheme_id=999", json={"name": "x"}
        )
        assert r.status_code == 404
