FROM python:3.13-slim-bookworm

EXPOSE 42000

# The installer requires curl (and certificates) to download the release archive
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates build-essential openssl libpq-dev

# Install UV
RUN pip install uv

# Keeps Python from generating .pyc files in the container
ENV PYTHONDONTWRITEBYTECODE=1

# Turns off buffering for easier container logging
ENV PYTHONUNBUFFERED=1

# Copy the project into the image
COPY . /app

# Sync the project into a new environment, using the frozen lockfile
WORKDIR /app
RUN uv sync --frozen

# Add entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV PATH="/app/.venv/bin:$PATH"

# Set random secret key
RUN export SECRET_KEY=`python -c 'import secrets; print(secrets.token_hex())'`

ENTRYPOINT ["/entrypoint.sh"]
# During debugging, this entry point will be overridden. For more information, please refer to https://aka.ms/vscode-docker-python-debug
CMD ["uv", "run", "gunicorn", "-w", "4", "--timeout", "120", "--reload", "--bind", "0.0.0.0:42000", "olim:app"]
