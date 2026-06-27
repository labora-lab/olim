# Contributing to OLIM

## Toolchain

The project standardizes on the Astral/`uv` stack — fast, single-purpose tools:

- **[uv](https://docs.astral.sh/uv/)** — package manager. `uv run <cmd>`, `uv add <pkg>`
  (dev deps: `uv add --dev <pkg>`). Don't hand-edit dependencies in `pyproject.toml`.
- **[ruff](https://docs.astral.sh/ruff/)** — linter + formatter.
- **[ty](https://github.com/astral-sh/ty)** — type checker.
- **[prek](https://prek.j178.dev)** — pre-commit hook runner.

Python **3.14** (see `.python-version`). Lazy annotations are native (PEP 649) — no
`from __future__ import annotations`.

## Getting set up

```sh
uv sync                    # install deps into .venv
docker compose up -d db    # Postgres for the app and the tests
uv run alembic upgrade head
prek install               # setup pre-commit hooks 
```

## Day-to-day

```sh
uv run fastapi dev                    # run the API locally (/docs for the UI)
uv run pytest                         # run the test suite
prek run --all-files                  # ty + ruff check + ruff format + tests
```

**Validate with `prek run --all-files`, not the individual tools** — it runs the same
hooks CI does (type check, lint, format, and the test suite).

## Tests

Tests live in `tests/`, split by kind:

- `tests/unit/` — pure logic, no I/O. Auto-marked `unit`; runs without a database.
- `tests/integration/` and `tests/api/` — hit a real Postgres. Auto-marked
  `integration`.

Integration tests use a dedicated `<db>_test` database (created automatically from
the schema; the dev database is never touched) and run inside a transaction that is
rolled back per test, so they stay isolated even when the code under test commits.
They need `docker compose up -d db`. Override the target with `TEST_DATABASE_URL`.

```sh
uv run pytest -m unit          # fast, no database
uv run pytest -m integration   # everything that needs Postgres
```

## Migrations

During early development there's no production data to preserve, so the preferred flow
when models change is to recreate the init migration from scratch:

```sh
docker compose down --volumes
rm -f alembic/versions/*.py
docker compose up -d db
uv run alembic revision --autogenerate -m init
uv run alembic upgrade head
```

## Commits

One line, conventional prefix (`feat:` / `fix:` / `chore:` / `docs:` / `test:`),
lowercase, no body. Example: `feat: annotation API with single-value answers`.
