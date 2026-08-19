# Using the REST API: Submitting Entries & Getting Predictions

OLIM ships a JSON REST API (`/api/v1`) that lets external systems submit text
entries and retrieve classifications from trained ML models, without going
through the web UI. This page walks through authentication, ingesting
entries, and requesting predictions.

!!! info "Prerequisite: a trained model"
    The API can only return predictions from a model that has already been
    **trained and has an active version**. Model creation and training are
    currently UI-only actions — go to a project's *Models* page
    (`/<project_id>/models`), create a model, link it to a label, and train
    it. Once a version is marked active, its `slug` can be used with the
    endpoints below.

## 1. Authenticate

All `/api/v1/*` endpoints (except generating a key) require a **user**-role
account and a Bearer token.

### Get an API key from the interface

1. Click the **gear icon** at the bottom of the left sidebar to open the
   Settings dropdown.
2. Select **Account Settings**.
3. Scroll to the **API Key** card.
4. Click **Generate API Key** (or **Regenerate API Key** if you already have
   one — this invalidates the old one and asks for confirmation).
5. The key appears in a masked field. Use the eye icon to reveal it and the
   clipboard icon to copy it.

!!! warning "Regenerating invalidates the old key"
    Any script or integration using the previous key will start getting
    `401 Unauthorized` as soon as you regenerate.

### Get an API key programmatically

=== "curl"

    ```bash
    curl -X POST http://localhost:42000/api/v1/auth/key \
      -H "Content-Type: application/json" \
      -d '{"username": "myuser", "password": "mypassword"}'
    ```

=== "Response"

    ```json
    {
      "status": "success",
      "data": {"api_key": "9f1c2e...redacted...a03b"}
    }
    ```

This endpoint also regenerates/invalidates the previous key, same as the UI
button.

### Use the key

Send it as a `Bearer` token on every subsequent request:

```
Authorization: Bearer 9f1c2e...redacted...a03b
```

!!! warning "Role required"
    Only accounts with the **`user`** role can call the ingestion and
    prediction endpoints. `annotator` and `guest` accounts can authenticate
    but will receive `401`/`403` on those routes.

## 2. Submit entries

Entries must exist in a **dataset** before you can request predictions for
them by ID (you can also predict on raw text without ever storing it — see
[step 3](#3-get-predictions)).

Each entry needs a unique `id` (string), a `text` field, and optional free-form
`metadata`.

### Option A — create a dataset and ingest in one call

=== "curl"

    ```bash
    curl -X POST http://localhost:42000/api/v1/datasets \
      -H "Authorization: Bearer $API_KEY" \
      -H "Content-Type: application/json" \
      -d '{
        "name": "My Dataset",
        "entries": [
          {"id": "e1", "text": "Patient reports chest pain.", "metadata": {"source": "triage"}},
          {"id": "e2", "text": "Routine checkup, no complaints."}
        ],
        "projects": [1]
      }'
    ```

=== "Response"

    ```json
    {
      "status": "success",
      "data": {
        "ingested": 2,
        "skipped": 0,
        "warnings": [],
        "dataset_id": 3
      }
    }
    ```

`projects` (optional) links the new dataset to one or more existing project
IDs.

### Option B — ingest into an existing dataset

```bash
curl -X POST http://localhost:42000/api/v1/datasets/3/entries \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "entries": [
      {"id": "e3", "text": "Follow-up visit, symptoms resolved."}
    ]
  }'
```

Duplicate IDs (already in the dataset, or repeated within the same request)
are skipped and reported back in `warnings`, not treated as errors.

!!! note "Limits"
    - Max **1000 entries** per ingest request.
    - Max **10,000 characters** per text when predicting (see below).

### List existing datasets

```bash
curl http://localhost:42000/api/v1/datasets \
  -H "Authorization: Bearer $API_KEY"
```

## 3. Get predictions

Look up a model's info (and confirm it has an active version) first:

```bash
curl http://localhost:42000/api/v1/models/my-model-slug \
  -H "Authorization: Bearer $API_KEY"
```

```json
{
  "status": "success",
  "data": {
    "slug": "my-model-slug",
    "name": "Chest Pain Classifier",
    "algorithm": "TfidfXGBoostClassifier",
    "status": "active",
    "active_version": 3,
    "created": "2024-01-15T10:30:00"
  }
}
```

There are three ways to request predictions, depending on where your text
comes from:

### a) Predict on a single raw text (no ingestion needed)

```bash
curl -X POST http://localhost:42000/api/v1/models/my-model-slug/predict \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"text": "Patient reports chest pain."}'
```

```json
{
  "status": "success",
  "data": {
    "predicted_class": "sim",
    "prediction_set": ["sim"],
    "confidence": 0.95,
    "probabilities": {"sim": 0.95, "não": 0.05},
    "model_slug": "my-model-slug",
    "model_version": 3
  }
}
```

### b) Predict on a batch of raw texts

```bash
curl -X POST http://localhost:42000/api/v1/models/my-model-slug/predict/batch \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"texts": ["Patient reports chest pain.", "Routine checkup, no complaints."]}'
```

Returns `{"predictions": [...], "total": 2}`, where each item has the same
shape as the single-prediction response. Max **1000 texts** per request.

### c) Predict on entries already stored in a dataset

Useful once you've ingested entries via step 2 and just want to classify
them by ID (no need to resend the text):

```bash
curl -X POST http://localhost:42000/api/v1/models/my-model-slug/predict/entries \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"entries": [{"entry_id": "e1", "dataset_id": 3}, {"entry_id": "e2", "dataset_id": 3}]}'
```

```json
{
  "status": "success",
  "data": {
    "predictions": [
      {
        "entry_id": "e1",
        "dataset_id": 3,
        "predicted_class": "sim",
        "prediction_set": ["sim"],
        "confidence": 0.95,
        "probabilities": {"sim": 0.95, "não": 0.05},
        "model_slug": "my-model-slug",
        "model_version": 3
      }
    ],
    "errors": [],
    "total_requested": 2,
    "total_predicted": 2
  }
}
```

Entries that don't exist, or fail during prediction, are reported per-item in
`errors` rather than failing the whole batch.

### Pinning a model version

All three prediction endpoints accept an optional `"version": <int>` field.
Omit it to use the model's current active version; pass a specific version
number to reproduce predictions from an older trained version.

## Response format & error handling

Every endpoint returns the same envelope:

```json
// success
{"status": "success", "data": { ... }}

// error
{"status": "error", "error": "human-readable message"}
```

Common status codes: `400` (validation error), `401`/`403` (missing or
insufficient auth), `404` (dataset/model/entry not found), `500` (server-side
failure, e.g. Elasticsearch unreachable).

## Endpoint reference

| Method | Path                                    | Purpose                                   |
| ------ | ---------------------------------------- | ------------------------------------------ |
| POST   | `/api/v1/auth/key`                       | Generate/regenerate an API key             |
| GET    | `/api/v1/datasets`                       | List datasets                              |
| POST   | `/api/v1/datasets`                       | Create a dataset + ingest entries          |
| POST   | `/api/v1/datasets/<dataset_id>/entries`  | Ingest entries into an existing dataset    |
| GET    | `/api/v1/models/<slug>`                  | Get model info (algorithm, active version) |
| POST   | `/api/v1/models/<slug>/predict`          | Predict a single raw text                  |
| POST   | `/api/v1/models/<slug>/predict/batch`    | Predict a list of raw texts                |
| POST   | `/api/v1/models/<slug>/predict/entries`  | Predict stored entries by ID               |
| GET    | `/api/v1/health`                         | Health check                               |

For implementation details, see the source in `olim/api_rest.py`.
