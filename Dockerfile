FROM python:3.10-slim

EXPOSE 42000

# Keeps Python from generating .pyc files in the container
ENV PYTHONDONTWRITEBYTECODE=1

# Turns off buffering for easier container logging
ENV PYTHONUNBUFFERED=1

# Install pip requirements
COPY requirements.txt .
RUN python -m pip install -r requirements.txt

WORKDIR /app
COPY . /app

USER root

RUN export SECRET_KEY=`python -c 'import secrets; print(secrets.token_hex())'`

# During debugging, this entry point will be overridden. For more information, please refer to https://aka.ms/vscode-docker-python-debug
CMD ["gunicorn", "--timeout", "120", "--reload", "--bind", "0.0.0.0:42000", "olim:app"]
