# OLIM - **O**pen **L**abeller for **I**terative **M**achine Learning

> Under heavy development.

An API for labeling datasets and training models on the labels. You create a
**dataset**, fill it with **items**, define a **scheme** of labeling questions, and
**annotate** the items - by hand today, by an LLM later. Then you compose a **training
pipeline** out of blocks (vectorize → split → train → evaluate) and **run** it over the
labels. The loop is iterative: label a batch, train, predict, label the next batch.

## What works today

### Labeling core

- **Datasets & items** - create a dataset, bulk-upload text items.
- **Schemes** - a labeling job over a dataset, created in one nested call: a scheme
  with its fields and (for selects) their options.
- **Fields** - four question types, each with its own config and validation:
  - `select` - pick one or many options; optional free-text (`allow_other`).
  - `numeric` - a number with optional `min` / `max` / `step`.
  - `text` - a free-text answer.
  - `boolean` - yes/no, optionally `nullable` (so "unknown" is a real answer).
- **Annotations** - answer fields for an item in one batch call. A single `value`
  per field is routed to the right typed column by the field's type. Upsert per
  `(item, field, source)`; multi-select reconciles the full option set; the batch is
  all-or-nothing. `source` defaults to `"human"` - the LLM path will reuse the same
  core with `source="llm"`.

### Training pipelines

- **Composition** - build a pipeline as an ordered list of typed **blocks** (clean,
  vectorize, split, model, eval, postprocess, store). Each block declares what data
  capabilities it *consumes* and *produces*; a "what fits next" engine offers only the
  blocks that are valid given the pipeline so far, and exposes each candidate's config
  schema. Per-block config is validated at the edge (discriminated union).
- **Execution** - run a pipeline as a background job. A Celery chain runs each block in
  order on a worker; data passes **by reference** through a pluggable artifact store
  (pickle on disk now, the path stored in the DB), so heavy data never crosses the
  broker. `PipelineRun` + `BlockRun` track status, timings, per-block metrics, and the
  exact blocks that ran (snapshotted, so editing the pipeline never rewrites history).
  Light vs. heavy blocks route to separate queues.
- **Real blocks** - one end-to-end path is implemented with scikit-learn: `tfidf →
  train_test_split → logreg → classification_metrics`, producing real accuracy / F1.
  The other blocks are scaffolded behind a runner-class factory and fill in one at a
  time.

The API is resource-driven: every id that isn't the resource's own goes in the query
string.

```
GET|POST /datasets                 GET /datasets/{id}
GET|POST /items?dataset_id=
GET|POST /schemes?dataset_id=
GET|POST /annotations?item_id=
GET|POST /pipelines?dataset_id=&scheme_id=    GET /pipelines/{id}
         GET  /pipelines/{id}/candidates
         POST /pipelines/{id}/blocks
GET|POST /pipelines/{id}/runs                 GET /runs/{id}
```

## Running it

The dev environment is Docker Compose: a Postgres `db`, an `init` step that runs the
migrations, the `api`, a `redis` broker, and a Celery `worker` that executes pipelines.

```sh
docker compose up -d --build
```

The API comes up on `http://localhost:7543` (`/docs` for the interactive OpenAPI UI).
See [`.env.example`](.env.example) for configuration.

To run the API against your own Postgres without Compose, set `DATABASE_URL` and:

```sh
uv run alembic upgrade head
uv run fastapi run
uv run celery -A olim.worker worker -Q light,heavy   # to execute pipelines
```

## Roadmap

The labeling core and the training-pipeline engine are in place. The larger goal is a
full iterative ML loop, plus the product surface around it.

**Done**

- [x] Labeling core - datasets, items, schemes, fields, annotations.
- [x] Pipeline composition - typed blocks, the "what fits next" compatibility engine,
      per-block config validation, candidate config schemas.
- [x] Pipeline execution - Celery + Redis, artifact-store by reference, `PipelineRun` /
      `BlockRun` tracking, light/heavy queues.
- [x] First real ML path - `tfidf → train_test_split → logreg → classification_metrics`
      on scikit-learn, behind an extensible runner-class factory.

**Next**

- [ ] **Fill in the remaining blocks** - clean (lowercase, stopwords), `count_vectorizer`,
      `random_forest` / `xgboost`, the 3-way `train_calib_test_split`, **conformal
      prediction** (per-class nonconformity quantiles), `pickle_artifact`.
- [ ] **Rethink block storage & data flow** - how blocks are persisted, how training
      data is loaded (currently all-in-RAM; needs streaming at scale), and how context
      is built and passed into each block (the accumulator contract).
- [ ] **Serving** - serve trained models for prediction over unlabeled items.
- [ ] **Surrogate model (LLM labeling)** - infer labels for unlabeled items: for each
      one, find similar labeled entries, ask an LLM to label it given that context plus
      the allowed labels, and store the inference with the LLM's signature and the
      context used (`source="llm"`).
- [ ] **Retraining triggers** - manual today; add scheduled / new-batch triggers.
- [ ] **Expose block outputs** - surface what each block produced via the API (maybe
      normalized out of the metrics JSONB).
- [ ] **User & auth system** - accounts, ownership, per-rater identity for annotations.
- [ ] **Web interface** - a UI to label items, compose pipelines, and watch runs.
- [ ] **Project documentation** - proper docs beyond this README: concepts, the API,
      how to add a block, and the architecture.

Each step carries real design decisions (data types, storage, CPU/GPU, distribution,
infra, defaults) - they're worked out as the loop is built.
