"""End-to-end HTTP tests for pipeline execution. Celery runs eager (inline, no
broker) so the chain executes within the test; artifacts go to a tmp dir, and
the real sklearn runners train on seeded labeled data.

The DB session is the rolled-back test session (see conftest)."""

from contextlib import contextmanager

import pytest

from olim import pipelines
from olim.worker import app as celery_app

_REAL_PATH = ("tfidf", "train_test_split", "logreg", "classification_metrics")


@pytest.fixture
def eager(tmp_path, monkeypatch, session):
    """Run the chain inline, share the rolled-back test session with the tasks,
    and write artifacts under a tmp dir."""
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True

    store = pipelines.LocalArtifactStore(tmp_path)
    monkeypatch.setattr("olim.tasks.runs.get_store", lambda: store)

    @contextmanager
    def shared_session():
        yield session

    monkeypatch.setattr("olim.tasks.runs.worker_session", shared_session)
    yield
    celery_app.conf.task_always_eager = False
    celery_app.conf.task_eager_propagates = False


def make_labeled_pipeline(client, block_types=_REAL_PATH):
    """A dataset with two trivially-separable classes, a select scheme, a label
    on every item, and a pipeline of the given blocks."""
    dataset_id = client.post("/datasets", json={"name": "d"}).json()["id"]

    texts = [("good " * 3) if i % 2 == 0 else ("bad " * 3) for i in range(20)]
    item_ids = client.post(
        f"/items?dataset_id={dataset_id}", json={"contents": texts}
    ).json()
    item_ids = [it["id"] for it in item_ids]

    scheme = client.post(
        f"/schemes?dataset_id={dataset_id}",
        json={
            "name": "s",
            "fields": [
                {
                    "type": "select",
                    "name": "label",
                    "options": [{"name": "good"}, {"name": "bad"}],
                }
            ],
        },
    ).json()
    field = scheme["fields"][0]
    good, bad = (o["id"] for o in field["options"])

    for i, item_id in enumerate(item_ids):
        opt = good if i % 2 == 0 else bad
        r = client.post(
            f"/annotations?item_id={item_id}",
            json={"answers": [{"field_id": field["id"], "value": opt}]},
        )
        assert r.status_code == 201, r.text

    pid = client.post(
        f"/pipelines?dataset_id={dataset_id}&scheme_id={scheme['id']}",
        json={"name": "p"},
    ).json()["id"]
    for t in block_types:
        r = client.post(f"/pipelines/{pid}/blocks", json={"type": t})
        assert r.status_code == 201, r.text
    return pid


class TestRun:
    def test_full_run_succeeds_and_records_each_block(self, client, eager):
        pid = make_labeled_pipeline(client)
        r = client.post(f"/pipelines/{pid}/runs")
        assert r.status_code == 201, r.text
        run = r.json()
        assert run["status"] == "succeeded"

        blocks = run["blocks"]
        assert [b["position"] for b in blocks] == [0, 1, 2, 3]
        assert all(b["status"] == "succeeded" for b in blocks)
        # the eval block produces only metrics (no heavy artifact)
        assert all(b["artifact_ref"] for b in blocks[:3])
        assert blocks[3]["artifact_ref"] is None
        # real metrics: trivially-separable classes -> near-perfect accuracy
        assert blocks[3]["metrics"]["accuracy"] >= 0.99
        assert "f1_macro" in blocks[3]["metrics"]

    def test_get_run_returns_nested_block_runs(self, client, eager):
        pid = make_labeled_pipeline(client)
        run_id = client.post(f"/pipelines/{pid}/runs").json()["id"]
        r = client.get(f"/runs/{run_id}")
        assert r.status_code == 200
        assert len(r.json()["blocks"]) == 4

    def test_run_history_newest_first(self, client, eager):
        pid = make_labeled_pipeline(client)
        first = client.post(f"/pipelines/{pid}/runs").json()["id"]
        second = client.post(f"/pipelines/{pid}/runs").json()["id"]
        r = client.get(f"/pipelines/{pid}/runs")
        ids = [run["id"] for run in r.json()]
        assert ids == [second, first]


class TestRunErrors:
    def test_running_empty_pipeline_is_422(self, client, eager):
        dataset_id = client.post("/datasets", json={"name": "d"}).json()["id"]
        scheme_id = client.post(
            f"/schemes?dataset_id={dataset_id}",
            json={"name": "s", "fields": [{"type": "text", "name": "t"}]},
        ).json()["id"]
        pid = client.post(
            f"/pipelines?dataset_id={dataset_id}&scheme_id={scheme_id}",
            json={"name": "p"},
        ).json()["id"]
        r = client.post(f"/pipelines/{pid}/runs")
        assert r.status_code == 422

    def test_running_missing_pipeline_is_404(self, client, eager):
        assert client.post("/pipelines/999/runs").status_code == 404

    def test_get_missing_run_is_404(self, client):
        assert client.get("/runs/999").status_code == 404
