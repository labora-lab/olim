FROM oven/bun:1-alpine AS web
WORKDIR /web

RUN apk add --no-cache nodejs

COPY web-client/package.json web-client/bun.lock* ./
RUN bun install --frozen-lockfile

COPY web-client/ .

RUN bun run build

FROM python:3.14-slim-trixie
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project

COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked

COPY --from=web /web/build/client/ /app/web-client/

ENV PATH="/app/.venv/bin:$PATH"

CMD ["fastapi", "run"]
