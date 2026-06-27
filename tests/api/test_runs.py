"""End-to-end HTTP tests for pipeline execution. Celery runs eager (inline, no
broker) so the chain executes within the test; artifacts go to a tmp dir.

The DB session is the rolled-back test session (see conftest)."""

from contextlib import contextmanager

import pytest

from olim import pipelines
from olim.worker import app as celery_app


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


def make_pipeline(client, block_types=("tfidf", "train_test_split", "logreg")):
    dataset_id = client.post("/datasets", json={"name": "d"}).json()["id"]
    scheme_id = client.post(
        f"/schemes?dataset_id={dataset_id}",
        json={
            "name": "s",
            "fields": [
                {
                    "type": "select",
                    "name": "f",
                    "options": [{"name": "a"}, {"name": "b"}],
                }
            ],
        },
    ).json()["id"]
    pid = client.post(
        f"/pipelines?dataset_id={dataset_id}&scheme_id={scheme_id}", json={"name": "p"}
    ).json()["id"]
    for t in block_types:
        r = client.post(f"/pipelines/{pid}/blocks", json={"type": t})
        assert r.status_code == 201, r.text
    return pid


class TestRun:
    def test_full_run_succeeds_and_records_each_block(self, client, eager):
        pid = make_pipeline(client)
        r = client.post(f"/pipelines/{pid}/runs")
        assert r.status_code == 201, r.text
        run = r.json()
        assert run["status"] == "succeeded"

        blocks = run["blocks"]
        assert [b["position"] for b in blocks] == [0, 1, 2]
        assert all(b["status"] == "succeeded" for b in blocks)
        assert all(b["artifact_ref"] for b in blocks)
        assert all(b["metrics"] == {"stub": True} for b in blocks)

    def test_get_run_returns_nested_block_runs(self, client, eager):
        pid = make_pipeline(client)
        run_id = client.post(f"/pipelines/{pid}/runs").json()["id"]
        r = client.get(f"/runs/{run_id}")
        assert r.status_code == 200
        assert len(r.json()["blocks"]) == 3

    def test_run_history_newest_first(self, client, eager):
        pid = make_pipeline(client)
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
