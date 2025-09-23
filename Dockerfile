FROM python:3.13-slim-bookworm

EXPOSE 42000

# The installer requires curl (and certificates) to download the release archive
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates build-essential openssl libpq-dev

# Install UV
RUN pip install uv

# Set user/group IDs (can be overridden via build args)
ARG USER_ID=1000
ARG GROUP_ID=1000

# Create a non-root user and group
RUN groupadd --gid ${GROUP_ID} olim && \
    useradd --uid ${USER_ID} --gid olim --shell /bin/bash --create-home olim

# Keeps Python from generating .pyc files in the container
ENV PYTHONDONTWRITEBYTECODE=1

# Turns off buffering for easier container logging
ENV PYTHONUNBUFFERED=1

# Add entrypoint script (needs to be in root filesystem)
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Create application directory with proper permissions
RUN mkdir -p /app /app/work /app/queues /app/uploads && \
    chown -R olim:olim /app

# Switch to non-root user early
USER olim
WORKDIR /app

# Copy dependency files and install as non-root user
COPY --chown=olim:olim pyproject.toml pyproject.toml
COPY --chown=olim:olim uv.lock uv.lock

RUN uv sync --frozen

# Copy application files
COPY --chown=olim:olim . /app

# Set PATH to include virtual environment
ENV PATH="/app/.venv/bin:$PATH"

# Set random secret key
RUN export SECRET_KEY=`python -c 'import secrets; print(secrets.token_hex())'`

ENTRYPOINT ["/entrypoint.sh"]
# During debugging, this entry point will be overridden. For more information, please refer to https://aka.ms/vscode-docker-python-debug
CMD ["uv", "run", "gunicorn", "-w", "4", "--timeout", "60", "--reload", "--bind", "0.0.0.0:42000", "olim:app"]
