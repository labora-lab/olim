FROM python:3.13-slim-bookworm

EXPOSE 42000

# Copy uv into the image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Keeps Python from generating .pyc files in the container
ENV PYTHONDONTWRITEBYTECODE=1

# Turns off buffering for easier container logging
ENV PYTHONUNBUFFERED=1

# Copy the project into the image
COPY . /app

# Sync the project into a new environment, using the frozen lockfile
WORKDIR /app
RUN uv sync --frozen

ENV PATH="/app/.venv/bin:$PATH"

# Set random secret key
RUN export SECRET_KEY=`python -c 'import secrets; print(secrets.token_hex())'`
# Compile babel translations
RUN uv run pybabel compile -d olim/translations

# During debugging, this entry point will be overridden. For more information, please refer to https://aka.ms/vscode-docker-python-debug
CMD ["uv", "run", "gunicorn", "--timeout", "120", "--reload", "--bind", "0.0.0.0:42000", "olim:app"]
