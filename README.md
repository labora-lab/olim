# OLIM - **O**pen **L**abeller for **I**terative **M**achine Learning

> Under heavy development.

An API for labeling datasets. You create a **dataset**, fill it with **items**, define
a **scheme** of labeling questions (fields of several types), and **annotate** the
items - by hand today, by an LLM later. The annotations feed an iterative training
loop: label a batch, train, predict, label the next batch.

## What works today

The labeling core is implemented and tested:

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
  all-or-nothing. `source` defaults to `"human"` - the future LLM path reuses the
  same core with `source="llm"`.

The API is resource-driven: every id that isn't the resource's own goes in the query
string.

```
GET|POST /datasets                 GET /datasets/{id}
GET|POST /items?dataset_id=
GET|POST /schemes?dataset_id=
GET|POST /annotations?item_id=
```

## Running it

The dev environment is Docker Compose: a Postgres `db`, an `init` step that runs the
migrations, and the `api`.

```sh
docker compose up -d --build
```

The API comes up on `http://localhost:7543` (`/docs` for the interactive OpenAPI UI).
See [`.env.example`](.env.example) for configuration.

To run the API against your own Postgres without Compose, set `DATABASE_URL` and:

```sh
uv run alembic upgrade head
uv run fastapi run
```

## Roadmap

The labeling core above is the foundation. The larger goal is a full iterative ML
loop on top of it:

1. **Training pipeline** - transform → vectorize → train/test split → fit. Retraining
   triggers (new labeled batch, scheduled, manual) and run tracking.
2. **Serving** - serve trained models for prediction over unlabeled items.
3. **Surrogate model (LLM)** - infer labels for unlabeled items: for each unlabeled
   entry, find similar labeled entries, ask an LLM to label it given that context plus
   the allowed labels, and store the inference with the LLM's signature and the
   context used.

Each step carries real design decisions (data types, storage, CPU/GPU, distribution,
infra, defaults) - they'll be worked out as the loop is built.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the toolchain and dev workflow, and
[CLAUDE.md](CLAUDE.md) for the architecture in detail.
