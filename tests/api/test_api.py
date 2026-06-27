"""End-to-end HTTP tests: routing, status codes, query-string ids, the pydantic
422 on bad field config, and the JSON error shape from the global handler.

The DB session is the rolled-back test session (see conftest), so these create
real rows without leaking between tests.
"""


def create_dataset(client, name="reviews"):
    r = client.post("/datasets", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def create_items(client, dataset_id, contents):
    r = client.post(f"/items?dataset_id={dataset_id}", json={"contents": contents})
    assert r.status_code == 201, r.text
    return [i["id"] for i in r.json()]


def create_scheme(client, dataset_id, body):
    r = client.post(f"/schemes?dataset_id={dataset_id}", json=body)
    assert r.status_code == 201, r.text
    return r.json()


class TestHappyPath:
    def test_full_flow_dataset_items_scheme_annotate(self, client):
        dataset_id = create_dataset(client)
        item_ids = create_items(client, dataset_id, ["a", "b"])
        scheme = create_scheme(
            client,
            dataset_id,
            {
                "name": "form",
                "fields": [
                    {
                        "type": "select",
                        "name": "sentiment",
                        "options": [{"name": "pos"}, {"name": "neg"}],
                    },
                    {
                        "type": "numeric",
                        "name": "score",
                        "min": 0,
                        "max": 10,
                        "step": 1,
                    },
                ],
            },
        )
        sentiment, score = scheme["fields"]
        pos = sentiment["options"][0]["id"]

        r = client.post(
            f"/annotations?item_id={item_ids[0]}",
            json={
                "answers": [
                    {"field_id": sentiment["id"], "value": pos},
                    {"field_id": score["id"], "value": 8},
                ]
            },
        )

        assert r.status_code == 201, r.text
        assert {a["value"] for a in r.json()} == {pos, 8.0}

    def test_get_dataset_returns_it(self, client):
        dataset_id = create_dataset(client, "x")
        r = client.get(f"/datasets/{dataset_id}")
        assert r.status_code == 200
        assert r.json()["name"] == "x"

    def test_multi_select_returns_one_row_per_option(self, client):
        dataset_id = create_dataset(client)
        (item_id,) = create_items(client, dataset_id, ["a"])
        scheme = create_scheme(
            client,
            dataset_id,
            {
                "name": "topics",
                "fields": [
                    {
                        "type": "select",
                        "name": "topics",
                        "multi": True,
                        "options": [{"name": "x"}, {"name": "y"}, {"name": "z"}],
                    }
                ],
            },
        )
        field = scheme["fields"][0]
        ids = [o["id"] for o in field["options"][:2]]

        r = client.post(
            f"/annotations?item_id={item_id}",
            json={"answers": [{"field_id": field["id"], "value": ids}]},
        )

        assert r.status_code == 201
        assert sorted(a["value"] for a in r.json()) == sorted(ids)


class TestErrors:
    def test_get_missing_dataset_is_404_with_detail(self, client):
        r = client.get("/datasets/999")
        assert r.status_code == 404
        assert "not found" in r.json()["detail"]

    def test_annotate_missing_item_is_404(self, client):
        r = client.post(
            "/annotations?item_id=999", json={"answers": [{"field_id": 1, "value": 1}]}
        )
        assert r.status_code == 404

    def test_bad_field_config_is_422_at_the_boundary(self, client):
        # `min` is not valid on a text field — pydantic's discriminated union
        # rejects it with extra="forbid" before any service runs.
        dataset_id = create_dataset(client)
        r = client.post(
            f"/schemes?dataset_id={dataset_id}",
            json={"name": "x", "fields": [{"type": "text", "name": "n", "min": 0}]},
        )
        assert r.status_code == 422

    def test_invalid_answer_is_422_with_field_errors(self, client):
        dataset_id = create_dataset(client)
        (item_id,) = create_items(client, dataset_id, ["a"])
        scheme = create_scheme(
            client,
            dataset_id,
            {
                "name": "s",
                "fields": [
                    {"type": "numeric", "name": "score", "min": 0, "max": 10, "step": 1}
                ],
            },
        )
        field_id = scheme["fields"][0]["id"]

        r = client.post(
            f"/annotations?item_id={item_id}",
            json={"answers": [{"field_id": field_id, "value": 99}]},
        )

        assert r.status_code == 422
        assert r.json()["detail"] == [
            {"field_id": field_id, "error": "value above max 10.0"}
        ]

    def test_all_or_nothing_saves_nothing_on_partial_failure(self, client):
        dataset_id = create_dataset(client)
        (item_id,) = create_items(client, dataset_id, ["a"])
        scheme = create_scheme(
            client,
            dataset_id,
            {
                "name": "s",
                "fields": [
                    {"type": "numeric", "name": "a", "min": 0, "max": 10, "step": 1},
                    {"type": "numeric", "name": "b", "min": 0, "max": 10, "step": 1},
                ],
            },
        )
        good, bad = (f["id"] for f in scheme["fields"])

        r = client.post(
            f"/annotations?item_id={item_id}",
            json={
                "answers": [
                    {"field_id": good, "value": 5},
                    {"field_id": bad, "value": 99},
                ]
            },
        )
        assert r.status_code == 422

        # nothing persisted: the valid answer was rolled back with the batch.
        back = client.get(f"/annotations?item_id={item_id}")
        assert back.json() == []
